from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from customers.models import Customer
from inventory.models import InventoryBalance, Product, ProductAttributeValue, StockLedger
from inventory.services import adjust_inventory, ensure_inventory_balance, get_default_warehouse
from .models import AuditLog, BusinessProfile, CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem, Payment, PaymentReversal, refresh_invoice_payment_status
from .tax_engine import calculate_gst, round_paise


MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")

SALES_UNIT_PIECE = "piece"
SALES_UNIT_MASTER_BOX = "master box"
SALES_UNIT_CHOICES = [SALES_UNIT_PIECE, SALES_UNIT_MASTER_BOX]
MASTER_BOX_ATTRIBUTE_CODE = "units_per_master_box"


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(value).quantize(QUANTITY_QUANTUM)


def _master_box_size(product):
    """Return the product's units_per_master_box value, or None."""
    value = (
        ProductAttributeValue.objects.filter(
            product=product,
            attribute_definition__code=MASTER_BOX_ATTRIBUTE_CODE,
            attribute_definition__is_active=True,
        )
        .values_list("value_integer", flat=True)
        .first()
    )
    if value is None or value <= 0:
        return None
    return value


def _validate_invoice_lines(line_items, customer=None):
    """Resolve each line's entered unit into an authoritative base quantity.

    Mirrors the purchase workflow exactly: the entered unit must be one of
    piece / master box; master box requires the product's
    units_per_master_box attribute and the submitted conversion factor must
    match it. Stock availability is checked against the converted base
    quantity, never the entered quantity.
    """
    product_ids = {item["product"].pk for item in line_items}
    products = Product.objects.select_for_update().in_bulk(product_ids)
    warehouse = get_default_warehouse()
    balances = {}
    for product_id in product_ids:
        balance = ensure_inventory_balance(product=products[product_id], warehouse=warehouse)
        balances[product_id] = InventoryBalance.objects.select_for_update().get(pk=balance.pk)
    requested_stock = defaultdict(lambda: Decimal("0"))

    for item in line_items:
        product = products[item["product"].pk]
        if not product.is_active:
            raise serializers.ValidationError({"line_items": f"{product.name} is inactive and cannot be sold."})
        quantity = Decimal(item["quantity"])
        rate_raw = item.get("rate_charged")
        if rate_raw is None or str(rate_raw).strip() == "":
            from customers.models import CustomerMRPPricing
            pricing = None
            if customer and product.mrp:
                pricing = CustomerMRPPricing.objects.filter(
                    customer=customer, mrp=product.mrp, is_active=True
                ).first()
            if pricing:
                rate = pricing.rate_per_piece
                item["rate_charged"] = rate
            else:
                raise serializers.ValidationError(
                    {"line_items": f"Rate charged is required for {product.name} (no MRP ₹{product.mrp} pricing configured for customer)."}
                )
        else:
            rate = Decimal(str(rate_raw))
        tax_rate = item.get("tax_rate")
        if quantity <= 0:
            raise serializers.ValidationError({"line_items": "Quantity must be greater than zero."})
        if rate < 0:
            raise serializers.ValidationError({"line_items": "Rate charged cannot be negative."})
        product_tax_rate = product.tax.rate if product.tax else Decimal("0")
        if tax_rate is not None and Decimal(str(tax_rate)) != product_tax_rate:
            raise serializers.ValidationError(
                {"line_items": f"Tax rate for {product.name} must match its configured GST rate of {product_tax_rate}%."}
            )

        sales_unit_name = str(item.get("sales_unit_name") or SALES_UNIT_PIECE).strip() or SALES_UNIT_PIECE
        conversion_factor = Decimal(str(item.get("conversion_factor", 1) or 1))
        if conversion_factor <= 0:
            raise serializers.ValidationError(
                {"line_items": f"Conversion factor for {product.name} must be positive."}
            )
        if sales_unit_name not in SALES_UNIT_CHOICES:
            raise serializers.ValidationError(
                {
                    "line_items": (
                        f"Unknown sales unit '{sales_unit_name}' for {product.name}; "
                        f"use 'piece' or 'master box'."
                    )
                }
            )
        if sales_unit_name == SALES_UNIT_MASTER_BOX:
            master_box = _master_box_size(product)
            if master_box is None:
                raise serializers.ValidationError(
                    {
                        "line_items": (
                            f"{product.name} has no master box size; sell it in base units."
                        )
                    }
                )
            if conversion_factor != master_box:
                raise serializers.ValidationError(
                    {
                        "line_items": (
                            f"Master box conversion for {product.name} must be {master_box} "
                            f"(got {conversion_factor})."
                        )
                    }
                )

        base_quantity = _quantity(quantity * conversion_factor)
        if base_quantity <= 0:
            raise serializers.ValidationError(
                {"line_items": f"Base quantity for {product.name} must be positive."}
            )
        item["base_quantity"] = base_quantity
        requested_stock[product.pk] += base_quantity

    for product_id, quantity in requested_stock.items():
        product = products[product_id]
        available = balances.get(product_id).quantity_on_hand if product_id in balances else Decimal("0.000")
        if quantity > available:
            raise serializers.ValidationError(
                {"line_items": f"Insufficient stock for {product.name}. Available: {available}."}
            )

    return products, balances


@transaction.atomic
def create_invoice(*, customer, invoice_number, notes="", created_by, payment_type, line_items, state=Invoice.STATE_POSTED, place_of_supply="", tax_mode=Invoice.TAX_MODE_EXCLUSIVE):
    if payment_type == "credit" and customer is None:
        raise serializers.ValidationError({"customer": "A registered customer is required for credit invoices."})
    if customer is not None:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)

    seller = BusinessProfile.objects.first()

    if state == Invoice.STATE_DRAFT:
        product_ids = {item["product"].pk for item in line_items}
        products = Product.objects.select_related('tax').in_bulk(product_ids)
        warehouse = get_default_warehouse()
        # Draft COGS pre-fill reads the authoritative WAC where a balance
        # exists; posting recomputes every snapshot from the live balance.
        draft_balances = {
            balance.product_id: balance
            for balance in InventoryBalance.objects.filter(
                product_id__in=product_ids, warehouse=warehouse
            )
        }
        balances = {
            product_id: draft_balances.get(product_id)
            or type("Balance", (), {"average_cost": Decimal("0.00")})()
            for product_id in product_ids
        }
        # Drafts validate conversion metadata but never touch stock; lines
        # keep their entered-unit representation for posting later.
        for item in line_items:
            quantity = Decimal(item["quantity"])
            if quantity <= 0:
                raise serializers.ValidationError({"line_items": "Quantity must be greater than zero."})
            sales_unit_name = str(item.get("sales_unit_name") or SALES_UNIT_PIECE).strip() or SALES_UNIT_PIECE
            conversion_factor = Decimal(str(item.get("conversion_factor", 1) or 1))
            if sales_unit_name not in SALES_UNIT_CHOICES:
                raise serializers.ValidationError(
                    {"line_items": f"Unknown sales unit '{sales_unit_name}'; use 'piece' or 'master box'."}
                )
            if sales_unit_name == SALES_UNIT_MASTER_BOX:
                master_box = _master_box_size(products[item["product"].pk])
                if master_box is None:
                    raise serializers.ValidationError(
                        {"line_items": f"{products[item['product'].pk].name} has no master box size; sell it in base units."}
                    )
                if conversion_factor != master_box:
                    raise serializers.ValidationError(
                        {"line_items": f"Master box conversion for {products[item['product'].pk].name} must be {master_box} (got {conversion_factor})."}
                    )
            elif conversion_factor <= 0:
                raise serializers.ValidationError({"line_items": "Conversion factor must be positive."})
            item["base_quantity"] = _quantity(quantity * conversion_factor)
            rate_raw = item.get("rate_charged")
            if rate_raw is None or str(rate_raw).strip() == "":
                from customers.models import CustomerMRPPricing
                pricing = None
                product_obj = products[item["product"].pk]
                if customer and product_obj.mrp:
                    pricing = CustomerMRPPricing.objects.filter(
                        customer=customer, mrp=product_obj.mrp, is_active=True
                    ).first()
                if pricing:
                    item["rate_charged"] = pricing.rate_per_piece
                else:
                    item["rate_charged"] = Decimal("0.00")
    else:
        products, balances = _validate_invoice_lines(line_items, customer=customer)

    calculated_lines_input = []
    for item in line_items:
        product = products[item["product"].pk]
        base_quantity = str(item["base_quantity"])
        rate_charged = str(item.get("rate_charged", 0))
        discount_amount = str(item.get("discount_amount", 0))
        tax_rate = str(item.get("tax_rate", product.tax.rate if product.tax else 0))

        calculated_lines_input.append({
            "product": product,
            "quantity": base_quantity,
            "rate_charged": rate_charged,
            "discount_amount": discount_amount,
            "tax_rate": tax_rate,
        })

    calc_result = calculate_gst(
        seller_profile=seller,
        customer=customer,
        lines=calculated_lines_input,
        place_of_supply_state_code=place_of_supply,
        tax_mode=tax_mode,
        rounding=round_paise,
    )

    total_amount = calc_result["totals"]["grand_total"]

    if payment_type == "credit" and customer is not None and customer.credit_limit:
        if customer.outstanding_balance + _money(total_amount) > customer.credit_limit:
            raise serializers.ValidationError(
                {"customer": f"Credit limit exceeded. Available credit: {_money(customer.credit_limit - customer.outstanding_balance)}."}
            )

    invoice = Invoice.objects.create(
        customer=customer,
        invoice_number=invoice_number,
        payment_type=payment_type,
        notes=notes,
        created_by=created_by,
        total_amount=total_amount,
        state=state,
        customer_name_snapshot=customer.name if customer else "Walk-in customer",
        customer_gstin_snapshot=customer.gstin or "" if customer else "",
        customer_registration_type_snapshot=customer.gst_registration_type if customer else "",
        customer_state_code_snapshot=customer.state_code or "" if customer else "",
        billing_address_snapshot=customer.billing_address or "" if customer else "",
        shipping_address_snapshot=customer.shipping_address or "" if customer else "",
        state_snapshot=customer.state or "" if customer else "",
        pincode_snapshot=customer.pincode or "" if customer else "",
        seller_business_name_snapshot=seller.business_name if seller else "",
        seller_gstin_snapshot=seller.gstin if seller else "",
        seller_address_snapshot=seller.registered_address if seller else "",
        seller_state_snapshot=seller.state if seller else "",
        seller_state_code_snapshot=seller.state_code if seller else "",
        place_of_supply=calc_result["place_of_supply"],
        tax_mode=calc_result["tax_mode"],
    )

    for idx, line_result in enumerate(calc_result["lines"]):
        item = line_items[idx]
        product = calculated_lines_input[idx]["product"]
        quantity = Decimal(str(item.get("quantity", 1)))
        base_quantity = item["base_quantity"]
        cost_price = balances[product.pk].average_cost
        cogs_amount = _money(base_quantity * cost_price)

        InvoiceLineItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            sales_unit_name=item.get("sales_unit_name") or SALES_UNIT_PIECE,
            conversion_factor=Decimal(str(item.get("conversion_factor", 1) or 1)),
            base_quantity=base_quantity,
            rate_charged=line_result["rate_charged"],
            discount_amount=line_result["discount_amount"],
            tax_rate=Decimal(str(calculated_lines_input[idx]["tax_rate"])),
            tax_amount=line_result["tax_amount"],
            cgst_rate=line_result["cgst_rate"],
            cgst_amount=line_result["cgst_amount"],
            sgst_rate=line_result["sgst_rate"],
            sgst_amount=line_result["sgst_amount"],
            igst_rate=line_result["igst_rate"],
            igst_amount=line_result["igst_amount"],
            line_total=line_result["line_total"],
            cost_price_snapshot=cost_price,
            cogs_amount=cogs_amount,
            product_name_snapshot=product.name,
            base_unit_snapshot=product.base_unit,
            hsn_sac_snapshot=product.hsn_sac,
            taxable_value_snapshot=line_result["taxable_value"],
            mrp_snapshot=product.mrp or Decimal("0.00"),
        )
        if state == Invoice.STATE_DRAFT:
            continue
        adjust_inventory(
            product=product,
            quantity_delta=-base_quantity,
            movement_type=StockLedger.SALE,
            created_by=created_by,
            reference_type="invoice",
            reference_id=invoice.pk,
            unit_cost=cost_price,
        )

    if state == Invoice.STATE_DRAFT:
        return invoice
    if payment_type == "cash":
        create_payment(customer=customer, invoice=invoice, amount=invoice.total_amount, actor=created_by)
    else:
        invoice.refresh_from_db()
    AuditLog.objects.create(user=created_by, action="invoice_posted", entity_type="Invoice", entity_id=invoice.pk)

    return invoice


@transaction.atomic
def post_invoice(*, invoice_id, posted_by):
    invoice = Invoice.objects.select_for_update().prefetch_related("line_items__product").get(pk=invoice_id)
    if invoice.state == Invoice.STATE_POSTED:
        return invoice
    if invoice.state != Invoice.STATE_DRAFT:
        raise serializers.ValidationError({"state": "Only draft invoices can be posted."})
    line_items = list(invoice.line_items.select_related("product"))
    products, balances = _validate_invoice_lines(
        [
            {
                "product": line.product,
                "quantity": line.quantity,
                "rate_charged": line.rate_charged,
                "tax_rate": line.tax_rate,
                "discount_amount": line.discount_amount,
                "sales_unit_name": line.sales_unit_name,
                "conversion_factor": line.conversion_factor,
            }
            for line in line_items
        ],
        customer=invoice.customer,
    )
    if (
        invoice.payment_type == Invoice.PAYMENT_TYPE_CREDIT
        and invoice.customer is not None
        and invoice.customer.credit_limit
    ):
        customer = Customer.objects.select_for_update().get(pk=invoice.customer_id)
        if customer.outstanding_balance + _money(invoice.total_amount) > customer.credit_limit:
            raise serializers.ValidationError(
                {"customer": f"Credit limit exceeded. Available credit: {_money(customer.credit_limit - customer.outstanding_balance)}."}
            )
    for line in line_items:
        product = products[line.product_id]
        line.cost_price_snapshot = balances[product.pk].average_cost
        line.cogs_amount = _money(line.base_quantity * line.cost_price_snapshot)
        line.product_name_snapshot = product.name
        line.base_unit_snapshot = product.base_unit
        line.mrp_snapshot = product.mrp or Decimal("0.00")
        line.save(update_fields=["cost_price_snapshot", "cogs_amount", "product_name_snapshot", "base_unit_snapshot", "mrp_snapshot"])
        adjust_inventory(product=product, quantity_delta=-line.base_quantity, movement_type=StockLedger.SALE, created_by=posted_by, reference_type="invoice", reference_id=invoice.pk, unit_cost=line.cost_price_snapshot)
    invoice.state = Invoice.STATE_POSTED
    invoice._allow_lifecycle_transition = True
    invoice.save(update_fields=["state", "updated_at"])
    if invoice.payment_type == Invoice.PAYMENT_TYPE_CASH:
        create_payment(customer=invoice.customer, invoice=invoice, amount=invoice.total_amount, actor=posted_by)
    AuditLog.objects.create(user=posted_by, action="invoice_posted", entity_type="Invoice", entity_id=invoice.pk)
    return invoice


@transaction.atomic
def create_credit_note(*, original_invoice, reason="", created_by, line_items):
    invoice = Invoice.objects.select_for_update().get(pk=original_invoice.pk)
    if invoice.state != Invoice.STATE_POSTED:
        raise serializers.ValidationError({"original_invoice": "Credit notes require a posted invoice."})
    original_lines = {
        line.pk: line
        for line in invoice.line_items.select_related("product").all()
    }
    product_ids = {item["product"].pk for item in line_items}
    products = Product.objects.select_for_update().in_bulk(product_ids)
    already_reversed = defaultdict(lambda: Decimal("0"))
    for reversal in CreditNoteLineItem.objects.filter(credit_note__original_invoice=invoice):
        already_reversed[reversal.invoice_line_item_id] += reversal.quantity

    calculated_lines = []
    total_amount = Decimal("0.00")
    for item in line_items:
        original_line = original_lines.get(item.get("invoice_line_item").pk if item.get("invoice_line_item") else None)
        if original_line is None or original_line.product_id != item["product"].pk:
            raise serializers.ValidationError({"line_items": "Each reversal must reference its original invoice line item and product."})
        raw_quantity = Decimal(item["quantity"])
        sales_unit = str(item.get("sales_unit_name") or "").strip().lower()
        if sales_unit == SALES_UNIT_MASTER_BOX:
            conversion_factor = original_line.conversion_factor
            quantity = _quantity(raw_quantity * conversion_factor)
        elif item.get("conversion_factor"):
            conversion_factor = Decimal(str(item["conversion_factor"]))
            quantity = _quantity(raw_quantity * conversion_factor)
        else:
            quantity = _quantity(raw_quantity)

        # Reversal quantities are base units, validated against the line's
        # converted base quantity; stock restoration uses them directly.
        if quantity <= 0 or already_reversed[original_line.pk] + quantity > original_line.base_quantity:
            raise serializers.ValidationError({"line_items": "A reversal cannot exceed the quantity originally billed."})
        product = products[original_line.product_id]
        tax_rate = original_line.tax_rate
        # Proportions compare in base units.
        base_quantity = original_line.base_quantity
        proportion = quantity / base_quantity
        per_base_rate = original_line.rate_charged
        discount_amount = _money(original_line.discount_amount * proportion)
        subtotal = _money((quantity * per_base_rate) - discount_amount)

        tax_amount = _money(original_line.tax_amount * proportion)
        line_total = _money(subtotal + tax_amount)

        cgst_amount = _money(original_line.cgst_amount * proportion)
        sgst_amount = _money(original_line.sgst_amount * proportion)
        igst_amount = _money(original_line.igst_amount * proportion)

        calculated_lines.append((original_line, product, quantity, discount_amount, tax_amount, cgst_amount, sgst_amount, igst_amount, line_total, per_base_rate))
        total_amount += line_total

    credit_note = CreditNote.objects.create(
        original_invoice=invoice,
        reason=reason,
        total_amount=_money(total_amount),
        created_by=created_by,
    )
    for original_line, product, quantity, discount_amount, tax_amount, cgst_amount, sgst_amount, igst_amount, line_total, per_base_rate in calculated_lines:
        CreditNoteLineItem.objects.create(
            credit_note=credit_note,
            invoice_line_item=original_line,
            product=product,
            quantity=quantity,
            rate_charged=_money(per_base_rate),
            discount_amount=discount_amount,
            tax_rate=original_line.tax_rate,
            tax_amount=tax_amount,
            cgst_rate=original_line.cgst_rate,
            cgst_amount=cgst_amount,
            sgst_rate=original_line.sgst_rate,
            sgst_amount=sgst_amount,
            igst_rate=original_line.igst_rate,
            igst_amount=igst_amount,
            line_total=line_total,
        )
        adjust_inventory(
            product=product,
            quantity_delta=quantity,
            movement_type=StockLedger.SALES_RETURN,
            created_by=created_by,
            reference_type="credit_note",
            reference_id=credit_note.pk,
            unit_cost=original_line.cost_price_snapshot,
        )

    return credit_note


@transaction.atomic
def cancel_invoice(*, invoice_id, cancelled_by, reason):
    invoice = Invoice.objects.select_for_update().prefetch_related("line_items").get(pk=invoice_id)
    if invoice.state == Invoice.STATE_CANCELLED:
        raise serializers.ValidationError({"state": "Invoice is already cancelled."})
    if invoice.state != Invoice.STATE_POSTED:
        raise serializers.ValidationError({"state": "Only posted invoices can be cancelled."})
    for line in invoice.line_items.select_related("product"):
        adjust_inventory(
            product=line.product,
            quantity_delta=line.base_quantity,
            movement_type=StockLedger.SALE_REVERSAL,
            created_by=cancelled_by,
            reference_type="invoice_cancellation",
            reference_id=invoice.pk,
            unit_cost=line.cost_price_snapshot,
            reason=reason,
        )
    invoice.state = Invoice.STATE_CANCELLED
    invoice._allow_lifecycle_transition = True
    invoice.cancelled_at = timezone.now()
    invoice.cancelled_by = cancelled_by
    invoice.cancellation_reason = reason
    invoice.save(update_fields=["state", "cancelled_at", "cancelled_by", "cancellation_reason", "updated_at"])
    AuditLog.objects.create(user=cancelled_by, action="invoice_cancelled", entity_type="Invoice", entity_id=invoice.pk, metadata={"reason": reason})
    return invoice


@transaction.atomic
def update_draft_invoice(*, invoice_id, customer, payment_type, line_items, notes="", updated_by, place_of_supply="", tax_mode=Invoice.TAX_MODE_EXCLUSIVE):
    """Replace all fields and lines of a DRAFT invoice.

    No stock, payment, ledger, or WAC changes — the draft is still uncommitted.
    Validation mirrors the draft-creation path exactly.
    """
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.state != Invoice.STATE_DRAFT:
        raise serializers.ValidationError({"state": "Only draft invoices can be edited."})

    if payment_type == "credit" and customer is None:
        raise serializers.ValidationError({"customer": "A registered customer is required for credit invoices."})
    if customer is not None:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)

    seller = BusinessProfile.objects.first()

    # Validate lines (draft path: no stock check, just metadata validation)
    product_ids = {item["product"].pk for item in line_items}
    products = Product.objects.select_related("tax").in_bulk(product_ids)
    warehouse = get_default_warehouse()
    draft_balances = {
        balance.product_id: balance
        for balance in InventoryBalance.objects.filter(product_id__in=product_ids, warehouse=warehouse)
    }
    balances = {
        product_id: draft_balances.get(product_id)
        or type("Balance", (), {"average_cost": Decimal("0.00")})()
        for product_id in product_ids
    }

    for item in line_items:
        quantity = Decimal(item["quantity"])
        if quantity <= 0:
            raise serializers.ValidationError({"line_items": "Quantity must be greater than zero."})
        sales_unit_name = str(item.get("sales_unit_name") or SALES_UNIT_PIECE).strip() or SALES_UNIT_PIECE
        conversion_factor = Decimal(str(item.get("conversion_factor", 1) or 1))
        if sales_unit_name not in SALES_UNIT_CHOICES:
            raise serializers.ValidationError(
                {"line_items": f"Unknown sales unit '{sales_unit_name}'; use 'piece' or 'master box'."}
            )
        if sales_unit_name == SALES_UNIT_MASTER_BOX:
            master_box = _master_box_size(products[item["product"].pk])
            if master_box is None:
                raise serializers.ValidationError(
                    {"line_items": f"{products[item['product'].pk].name} has no master box size; sell it in base units."}
                )
            if conversion_factor != master_box:
                raise serializers.ValidationError(
                    {"line_items": f"Master box conversion for {products[item['product'].pk].name} must be {master_box} (got {conversion_factor})."}
                )
        elif conversion_factor <= 0:
            raise serializers.ValidationError({"line_items": "Conversion factor must be positive."})
        item["base_quantity"] = _quantity(quantity * conversion_factor)

    # Build GST calculation inputs
    calculated_lines_input = []
    for item in line_items:
        product = products[item["product"].pk]
        calculated_lines_input.append({
            "product": product,
            "quantity": str(item["base_quantity"]),
            "rate_charged": str(item.get("rate_charged", 0)),
            "discount_amount": str(item.get("discount_amount", 0)),
            "tax_rate": str(item.get("tax_rate", product.tax.rate if product.tax else 0)),
        })

    calc_result = calculate_gst(
        seller_profile=seller,
        customer=customer,
        lines=calculated_lines_input,
        place_of_supply_state_code=place_of_supply,
        tax_mode=tax_mode,
        rounding=round_paise,
    )

    total_amount = calc_result["totals"]["grand_total"]

    # Delete existing lines (permitted for DRAFT by model)
    invoice.line_items.all().delete()

    # Update the invoice header — update only mutable fields (state is DRAFT, so
    # financial snapshots are still writable)
    invoice.customer = customer
    invoice.payment_type = payment_type
    invoice.notes = notes
    invoice.total_amount = total_amount
    invoice.place_of_supply = calc_result["place_of_supply"]
    invoice.tax_mode = calc_result["tax_mode"]
    invoice.customer_name_snapshot = customer.name if customer else "Walk-in customer"
    invoice.customer_gstin_snapshot = customer.gstin or "" if customer else ""
    invoice.customer_registration_type_snapshot = customer.gst_registration_type if customer else ""
    invoice.customer_state_code_snapshot = customer.state_code or "" if customer else ""
    invoice.billing_address_snapshot = customer.billing_address or "" if customer else ""
    invoice.shipping_address_snapshot = customer.shipping_address or "" if customer else ""
    invoice.state_snapshot = customer.state or "" if customer else ""
    invoice.pincode_snapshot = customer.pincode or "" if customer else ""
    invoice.seller_business_name_snapshot = seller.business_name if seller else ""
    invoice.seller_gstin_snapshot = seller.gstin if seller else ""
    invoice.seller_address_snapshot = seller.registered_address if seller else ""
    invoice.seller_state_snapshot = seller.state if seller else ""
    invoice.seller_state_code_snapshot = seller.state_code if seller else ""
    invoice.save(update_fields=[
        "customer", "payment_type", "notes", "total_amount",
        "place_of_supply", "tax_mode",
        "customer_name_snapshot", "customer_gstin_snapshot", "customer_registration_type_snapshot",
        "customer_state_code_snapshot", "billing_address_snapshot", "shipping_address_snapshot",
        "state_snapshot", "pincode_snapshot",
        "seller_business_name_snapshot", "seller_gstin_snapshot", "seller_address_snapshot",
        "seller_state_snapshot", "seller_state_code_snapshot",
        "updated_at",
    ])

    # Recreate lines (no stock adjustment for DRAFT)
    for idx, line_result in enumerate(calc_result["lines"]):
        item = line_items[idx]
        product = calculated_lines_input[idx]["product"]
        quantity = Decimal(str(item.get("quantity", 1)))
        base_quantity = item["base_quantity"]
        cost_price = balances[product.pk].average_cost
        cogs_amount = _money(base_quantity * cost_price)

        InvoiceLineItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            sales_unit_name=item.get("sales_unit_name") or SALES_UNIT_PIECE,
            conversion_factor=Decimal(str(item.get("conversion_factor", 1) or 1)),
            base_quantity=base_quantity,
            rate_charged=line_result["rate_charged"],
            discount_amount=line_result["discount_amount"],
            tax_rate=Decimal(str(calculated_lines_input[idx]["tax_rate"])),
            tax_amount=line_result["tax_amount"],
            cgst_rate=line_result["cgst_rate"],
            cgst_amount=line_result["cgst_amount"],
            sgst_rate=line_result["sgst_rate"],
            sgst_amount=line_result["sgst_amount"],
            igst_rate=line_result["igst_rate"],
            igst_amount=line_result["igst_amount"],
            line_total=line_result["line_total"],
            cost_price_snapshot=cost_price,
            cogs_amount=cogs_amount,
            product_name_snapshot=product.name,
            base_unit_snapshot=product.base_unit,
            hsn_sac_snapshot=product.hsn_sac,
            taxable_value_snapshot=line_result["taxable_value"],
            mrp_snapshot=product.mrp or Decimal("0.00"),
        )

    AuditLog.objects.create(
        user=updated_by,
        action="invoice_draft_updated",
        entity_type="Invoice",
        entity_id=invoice.pk,
        metadata={"invoice_number": invoice.invoice_number},
    )
    invoice.refresh_from_db()
    return invoice


def check_invoice_correction_eligibility(invoice_id):
    """Return (eligible: bool, reason: str) for the amendment workflow.

    Blocks if:
    - A replacement already exists (checked first — most informative for amended invoices)
    - Invoice is not POSTED
    - Any credit note exists (stock may have already been partially restored)
    - Any payment exists (prevents accounting ambiguity in V1)
    """
    try:
        invoice = Invoice.objects.prefetch_related("credit_notes", "payments").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        return False, "Invoice not found."

    # One replacement per invoice — check this first so amended invoices get an
    # informative message even though they are also CANCELLED.
    if invoice.replacement_invoice_id is not None:
        return False, "A replacement invoice already exists for this invoice."

    if invoice.state == Invoice.STATE_CANCELLED:
        return False, "Invoice is already cancelled."
    if invoice.state == Invoice.STATE_DRAFT:
        return False, "Draft invoices cannot be amended — edit them instead."
    if invoice.state != Invoice.STATE_POSTED:
        return False, "Only posted invoices can be corrected."

    # Credit note protection — partial reversals complicate cancellation
    if invoice.credit_notes.exists():
        return False, "Correction unavailable: credit note already issued against this invoice."

    # Payment protection — no automatic transfer in V1
    if invoice.payments.exists():
        return False, "Correction unavailable: payment already recorded."

    return True, ""



@transaction.atomic
def amend_invoice(*, invoice_id, corrected_line_items, customer, payment_type, notes="", place_of_supply="", tax_mode=Invoice.TAX_MODE_EXCLUSIVE, new_invoice_number, amended_by, reason):
    """Correct a posted invoice with no payments or credit notes.

    Atomically:
    1. Re-validates eligibility (inside the DB lock).
    2. Cancels the original (stock reversal).
    3. Creates a replacement invoice (new number, new stock deduction).
    4. Links original ↔ replacement.
    5. Writes a single audit event linking both.
    """
    # Re-validate inside the lock
    invoice = Invoice.objects.select_for_update().prefetch_related("credit_notes", "payments", "line_items").get(pk=invoice_id)

    if invoice.state != Invoice.STATE_POSTED:
        raise serializers.ValidationError({"state": "Only posted invoices can be corrected."})
    if invoice.replacement_invoice_id is not None:
        raise serializers.ValidationError({"invoice": "A replacement invoice already exists for this invoice."})
    if invoice.credit_notes.exists():
        raise serializers.ValidationError({"invoice": "Correction blocked: a credit note has been issued against this invoice."})
    if invoice.payments.exists():
        raise serializers.ValidationError({"invoice": "Correction blocked: a payment has been recorded against this invoice."})

    # Step 1: Cancel original (stock reversal)
    cancel_invoice(invoice_id=invoice_id, cancelled_by=amended_by, reason=f"[AMENDMENT] {reason}")

    # Step 2: Create replacement invoice (full posted workflow with stock deduction)
    replacement = create_invoice(
        customer=customer,
        invoice_number=new_invoice_number,
        notes=notes,
        created_by=amended_by,
        payment_type=payment_type,
        line_items=corrected_line_items,
        state=Invoice.STATE_POSTED,
        place_of_supply=place_of_supply,
        tax_mode=tax_mode,
    )

    # Step 3: Link the two invoices
    original = Invoice.objects.select_for_update().get(pk=invoice_id)
    original.replacement_invoice = replacement
    original.save(update_fields=["replacement_invoice", "updated_at"])

    replacement = Invoice.objects.select_for_update().get(pk=replacement.pk)
    replacement.amended_from_invoice = original
    replacement.save(update_fields=["amended_from_invoice", "updated_at"])

    # Step 4: Audit event linking both
    AuditLog.objects.create(
        user=amended_by,
        action="invoice_amended",
        entity_type="Invoice",
        entity_id=original.pk,
        metadata={
            "original_invoice_id": original.pk,
            "original_invoice_number": original.invoice_number,
            "replacement_invoice_id": replacement.pk,
            "replacement_invoice_number": replacement.invoice_number,
            "reason": reason,
        },
    )

    original.refresh_from_db()
    replacement.refresh_from_db()
    return original, replacement



@transaction.atomic
def reverse_payment(*, payment_id, amount, reversed_by, reason):
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    amount = _money(amount)
    reversed_amount = PaymentReversal.objects.filter(payment=payment).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    if amount <= 0 or reversed_amount + amount > payment.amount:
        raise serializers.ValidationError({"amount": "Reversal exceeds the remaining payment amount."})
    reversal = PaymentReversal.objects.create(payment=payment, amount=amount, reason=reason, reversed_by=reversed_by)
    if payment.invoice_id:
        refresh_invoice_payment_status(payment.invoice)
    AuditLog.objects.create(user=reversed_by, action="payment_reversed", entity_type="Payment", entity_id=payment.pk, metadata={"amount": str(amount), "reason": reason})
    return reversal


@transaction.atomic
def create_payment(*, customer, invoice, amount, actor, notes="", payment_method=Payment.METHOD_CASH, reference_number=""):
    amount = _money(amount)
    if amount <= 0:
        raise serializers.ValidationError({"amount": "Payment amount must be greater than zero."})
    if invoice is not None:
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.state != Invoice.STATE_POSTED:
            raise serializers.ValidationError({"invoice": "Payments can only be recorded against posted invoices."})
        if customer is not None and invoice.customer_id != customer.pk:
            raise serializers.ValidationError({"invoice": "This invoice does not belong to the selected customer."})
    payment = Payment.objects.create(
        customer=customer,
        invoice=invoice,
        amount=amount,
        payment_method=payment_method,
        reference_number=reference_number,
        notes=notes,
    )
    AuditLog.objects.create(user=actor, action="payment_received", entity_type="Payment", entity_id=payment.pk)
    return payment


def build_selected_invoices_item_summary(invoice_ids):
    """Authoritative item-wise quantity summary of selected POSTED invoices.

    Validates that invoice_ids is a non-empty list of integers.
    Filters exclusively Invoice.STATE_POSTED invoices.
    Aggregates base_quantity (base units/pieces) grouped by Product.id in ORM.
    """
    if not invoice_ids or not isinstance(invoice_ids, (list, tuple)):
        raise serializers.ValidationError({"invoice_ids": ["A non-empty list of invoice IDs is required."]})

    clean_ids = []
    for item in invoice_ids:
        try:
            val = int(item)
            clean_ids.append(val)
        except (ValueError, TypeError):
            raise serializers.ValidationError({"invoice_ids": ["All invoice IDs must be valid integers."]})

    if not clean_ids:
        raise serializers.ValidationError({"invoice_ids": ["A non-empty list of invoice IDs is required."]})

    deduped_ids = list(dict.fromkeys(clean_ids))

    posted_invoices = Invoice.objects.filter(
        id__in=deduped_ids,
        state=Invoice.STATE_POSTED,
    ).order_by("invoice_number")

    posted_ids = list(posted_invoices.values_list("id", flat=True))
    invoice_numbers = list(posted_invoices.values_list("invoice_number", flat=True))

    if not posted_ids:
        return {
            "selected_invoice_count": 0,
            "invoice_count": 0,
            "selected_invoice_numbers": [],
            "invoice_numbers": [],
            "total_products": 0,
            "total_base_quantity": "0.000",
            "items": [],
        }

    lines = InvoiceLineItem.objects.filter(
        invoice_id__in=posted_ids,
        invoice__state=Invoice.STATE_POSTED,
    )

    from django.db.models import Count, Max
    from django.db.models.functions import Coalesce

    rows = (
        lines.values(
            "product_id",
            "product__name",
            "product__sku",
            "product__mrp",
            "product__base_unit",
            "product__unit_type",
            "product__category",
            "product__brand",
        )
        .annotate(
            total_base_quantity=Coalesce(Sum("base_quantity"), Decimal("0.000")),
            invoice_count=Count("invoice_id", distinct=True),
            latest_mrp=Max("mrp_snapshot"),
            latest_name_snapshot=Max("product_name_snapshot"),
        )
        .order_by("product__name", "product_id")
    )

    product_ids = [r["product_id"] for r in rows]
    p_attrs = {}
    for pav in (
        ProductAttributeValue.objects.filter(product_id__in=product_ids)
        .select_related("attribute_definition", "value_choice")
    ):
        if pav.product_id not in p_attrs:
            p_attrs[pav.product_id] = {}
        p_attrs[pav.product_id][pav.attribute_definition.code] = pav.typed_value()

    items = []
    grand_total_base = Decimal("0.000")
    for r in rows:
        pid = r["product_id"]
        attrs = p_attrs.get(pid, {})
        mrp = r["product__mrp"] if r["product__mrp"] is not None else r["latest_mrp"]
        total_qty = r["total_base_quantity"] or Decimal("0.000")
        grand_total_base += total_qty

        variant_parts = []
        net_weight = attrs.get("net_weight")
        if net_weight:
            try:
                nw = float(net_weight)
                if nw < 1:
                    g = nw * 1000
                    variant_parts.append(f"{int(g) if g.is_integer() else round(g, 1)} g")
                else:
                    variant_parts.append(f"{int(nw) if nw.is_integer() else round(nw, 3)} kg")
            except (ValueError, TypeError):
                variant_parts.append(str(net_weight))
        if mrp is not None:
            variant_parts.append(f"MRP ₹{Decimal(str(mrp)):.2f}")
        if r["product__sku"]:
            variant_parts.append(f"SKU: {r['product__sku']}")
        if r["product__category"]:
            variant_parts.append(r["product__category"])

        prod_name = r["product__name"] or r["latest_name_snapshot"] or f"Product #{pid}"

        items.append(
            {
                "product_id": pid,
                "product_name": prod_name,
                "name": prod_name,
                "sku": r["product__sku"] or "",
                "mrp": str(mrp) if mrp is not None else None,
                "base_unit": r["product__base_unit"] or "piece",
                "unit_type": r["product__unit_type"] or "piece",
                "total_base_quantity": str(total_qty),
                "invoice_count": r["invoice_count"],
                "number_of_selected_invoices": r["invoice_count"],
                "variant_summary": " · ".join(variant_parts),
                "attributes": attrs,
            }
        )

    return {
        "selected_invoice_count": len(posted_ids),
        "invoice_count": len(posted_ids),
        "selected_invoice_numbers": invoice_numbers,
        "invoice_numbers": invoice_numbers,
        "total_products": len(items),
        "total_base_quantity": str(grand_total_base),
        "items": items,
    }


def build_item_summary_xlsx(summary_data):
    """Generate professional Excel workbook for the item-wise summary."""
    import io
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Item-wise Summary"

    title_font = Font(name="Calibri", size=14, bold=True, color="1E382B")
    subtitle_font = Font(name="Calibri", size=11, bold=True, color="2C4D3B")
    meta_label_font = Font(name="Calibri", size=10, bold=True, color="55695E")
    meta_val_font = Font(name="Calibri", size=10, bold=False, color="1E382B")
    header_font = Font(name="Calibri", size=11, bold=True, color="1E382B")
    header_fill = PatternFill(start_color="E6EFE9", end_color="E6EFE9", fill_type="solid")
    data_font = Font(name="Calibri", size=10)
    total_font = Font(name="Calibri", size=11, bold=True, color="1E382B")
    total_fill = PatternFill(start_color="F2F6F3", end_color="F2F6F3", fill_type="solid")
    note_font = Font(name="Calibri", size=9, italic=True, color="687E71")

    thin_border = Border(
        left=Side(style="thin", color="D4DED6"),
        right=Side(style="thin", color="D4DED6"),
        top=Side(style="thin", color="D4DED6"),
        bottom=Side(style="thin", color="D4DED6"),
    )
    header_border = Border(
        left=Side(style="thin", color="B0C4B8"),
        right=Side(style="thin", color="B0C4B8"),
        top=Side(style="medium", color="2C4D3B"),
        bottom=Side(style="medium", color="2C4D3B"),
    )
    total_border = Border(
        top=Side(style="thin", color="2C4D3B"),
        bottom=Side(style="double", color="2C4D3B"),
    )

    # 1. Header block
    ws["A1"] = "DIVYA ENTERPRISES"
    ws["A1"].font = title_font

    ws["A2"] = "ITEM-WISE SUMMARY OF SELECTED INVOICES"
    ws["A2"].font = subtitle_font

    inv_nums = summary_data.get("selected_invoice_numbers") or summary_data.get("invoice_numbers") or []
    ws["A3"] = "Selected Invoices:"
    ws["A3"].font = meta_label_font
    ws["B3"] = ", ".join(inv_nums) if inv_nums else "None"
    ws["B3"].font = meta_val_font

    ws["A4"] = "Generated At:"
    ws["A4"].font = meta_label_font
    ws["B4"] = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    ws["B4"].font = meta_val_font

    # 2. Table Headers (Row 6)
    headers = [
        "Product",
        "SKU",
        "Variant/Pack",
        "MRP",
        "Total Quantity",
        "Base Unit",
        "Invoice Count",
    ]
    header_row = 6
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = Alignment(
            horizontal="right" if h in {"MRP", "Total Quantity", "Invoice Count"} else ("center" if h == "Base Unit" else "left"),
            vertical="center",
            wrap_text=True,
        )

    # 3. Data rows
    items = summary_data.get("items", [])
    current_row = header_row + 1
    for item in items:
        # Product
        c1 = ws.cell(row=current_row, column=1, value=item.get("product_name") or item.get("name", ""))
        c1.font = data_font
        c1.border = thin_border
        c1.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        # SKU
        c2 = ws.cell(row=current_row, column=2, value=item.get("sku", ""))
        c2.font = data_font
        c2.border = thin_border
        c2.alignment = Alignment(horizontal="left", vertical="center")

        # Variant/Pack
        c3 = ws.cell(row=current_row, column=3, value=item.get("variant_summary", ""))
        c3.font = data_font
        c3.border = thin_border
        c3.alignment = Alignment(horizontal="left", vertical="center")

        # MRP
        mrp_raw = item.get("mrp")
        mrp_val = float(mrp_raw) if mrp_raw is not None else None
        c4 = ws.cell(row=current_row, column=4, value=mrp_val)
        c4.font = data_font
        c4.border = thin_border
        c4.alignment = Alignment(horizontal="right", vertical="center")
        if mrp_val is not None:
            c4.number_format = "#,##0.00"

        # Total Quantity (numeric)
        qty_raw = item.get("total_base_quantity", "0")
        qty_val = float(Decimal(str(qty_raw)))
        c5 = ws.cell(row=current_row, column=5, value=qty_val)
        c5.font = data_font
        c5.border = thin_border
        c5.alignment = Alignment(horizontal="right", vertical="center")
        c5.number_format = "#,##0.000" if (qty_val % 1 != 0) else "#,##0"

        # Base Unit
        c6 = ws.cell(row=current_row, column=6, value=item.get("base_unit", "piece"))
        c6.font = data_font
        c6.border = thin_border
        c6.alignment = Alignment(horizontal="center", vertical="center")

        # Invoice Count
        inv_count_val = int(item.get("invoice_count", 0))
        c7 = ws.cell(row=current_row, column=7, value=inv_count_val)
        c7.font = data_font
        c7.border = thin_border
        c7.alignment = Alignment(horizontal="right", vertical="center")
        c7.number_format = "#,##0"

        current_row += 1

    # 4. Totals Row
    tot_row = current_row
    ws.cell(row=tot_row, column=1, value="Total Products:").font = total_font
    ws.cell(row=tot_row, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.cell(row=tot_row, column=1).fill = total_fill
    ws.cell(row=tot_row, column=1).border = total_border

    ws.cell(row=tot_row, column=2, value=int(summary_data.get("total_products", len(items)))).font = total_font
    ws.cell(row=tot_row, column=2).alignment = Alignment(horizontal="left", vertical="center")
    ws.cell(row=tot_row, column=2).fill = total_fill
    ws.cell(row=tot_row, column=2).border = total_border

    ws.cell(row=tot_row, column=3, value="Total Base Quantity:").font = total_font
    ws.cell(row=tot_row, column=3).alignment = Alignment(horizontal="right", vertical="center")
    ws.cell(row=tot_row, column=3).fill = total_fill
    ws.cell(row=tot_row, column=3).border = total_border

    ws.cell(row=tot_row, column=4, value="").fill = total_fill
    ws.cell(row=tot_row, column=4).border = total_border

    tot_qty_val = float(Decimal(str(summary_data.get("total_base_quantity", "0"))))
    tot_qty_cell = ws.cell(row=tot_row, column=5, value=tot_qty_val)
    tot_qty_cell.font = total_font
    tot_qty_cell.fill = total_fill
    tot_qty_cell.border = total_border
    tot_qty_cell.alignment = Alignment(horizontal="right", vertical="center")
    tot_qty_cell.number_format = "#,##0.000" if (tot_qty_val % 1 != 0) else "#,##0"

    ws.cell(row=tot_row, column=6, value="piece").fill = total_fill
    ws.cell(row=tot_row, column=6).border = total_border
    ws.cell(row=tot_row, column=6).font = total_font
    ws.cell(row=tot_row, column=6).alignment = Alignment(horizontal="center", vertical="center")

    ws.cell(row=tot_row, column=7, value="").fill = total_fill
    ws.cell(row=tot_row, column=7).border = total_border

    # 5. Footnote
    note_cell = ws.cell(
        row=tot_row + 2,
        column=1,
        value="Quantities are aggregated in base units across the selected posted invoices.",
    )
    note_cell.font = note_font

    # 6. Autofilter and Freeze Panes
    ws.auto_filter.ref = f"A{header_row}:G{max(header_row, current_row - 1)}"
    ws.freeze_panes = f"A{header_row + 1}"

    # 7. Column Widths
    col_widths = {
        "A": 32,
        "B": 16,
        "C": 30,
        "D": 12,
        "E": 18,
        "F": 12,
        "G": 14,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
