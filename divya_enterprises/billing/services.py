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
from .tax_engine import calculate_gst


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


def _validate_invoice_lines(line_items):
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
        rate = Decimal(item["rate_charged"])
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
    else:
        products, balances = _validate_invoice_lines(line_items)

    calculated_lines_input = []
    for item in line_items:
        product = products[item["product"].pk]
        quantity = str(item.get("quantity", 1))
        rate_charged = str(item.get("rate_charged", 0))
        discount_amount = str(item.get("discount_amount", 0))
        tax_rate = str(item.get("tax_rate", product.tax.rate if product.tax else 0))

        calculated_lines_input.append({
            "product": product,
            "quantity": quantity,
            "rate_charged": rate_charged,
            "discount_amount": discount_amount,
            "tax_rate": tax_rate,
        })

    calc_result = calculate_gst(
        seller_profile=seller,
        customer=customer,
        lines=calculated_lines_input,
        place_of_supply_state_code=place_of_supply,
        tax_mode=tax_mode
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
        quantity = Decimal(line_result["quantity"])
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
        ]
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
        line.save(update_fields=["cost_price_snapshot", "cogs_amount", "product_name_snapshot", "base_unit_snapshot"])
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
        # Proportions compare in base units so master-box lines (rate per
        # box, entered quantity 2, base 384) reverse correctly.
        base_quantity = original_line.base_quantity
        proportion = quantity / base_quantity
        per_base_rate = original_line.rate_charged / original_line.conversion_factor
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
