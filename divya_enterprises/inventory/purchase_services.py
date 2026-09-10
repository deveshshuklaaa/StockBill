"""Purchase invoice lifecycle: draft → posted → cancelled.

The purchase workflow reuses the audited inventory foundations:
- adjust_inventory() owns all StockLedger entries and balance quantity changes
- weighted-average cost is maintained on InventoryBalance per warehouse
- Product.current_stock is only ever a resynchronized cache

Costing policy (V1): inventory cost is the pre-tax, post-discount taxable
value per base unit. GST is assumed ITC-recoverable (D1) and excluded from
the weighted-average cost basis. The per-unit rate and tax mode are
transaction-level inputs, never assumed from the catalogue or supplier.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection, models, transaction
from django.utils import timezone
from rest_framework import serializers

from billing.models import AuditLog, BusinessProfile
from billing.tax_engine import calculate_gst, round_paise

from .models import (
    InventoryBalance,
    Product,
    ProductAttributeValue,
    PurchaseInvoice,
    PurchaseLineItem,
    StockLedger,
    Supplier,
    Warehouse,
)
from .purchase_numbering import next_purchase_number
from .services import ensure_inventory_balance, get_default_warehouse


MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")
MASTER_BOX_ATTRIBUTE_CODE = "units_per_master_box"

PURCHASE_UNIT_PIECE = "piece"
PURCHASE_UNIT_MASTER_BOX = "master box"
PURCHASE_UNIT_CHOICES = [PURCHASE_UNIT_PIECE, PURCHASE_UNIT_MASTER_BOX]


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(value).quantize(QUANTITY_QUANTUM)


class _SupplierTaxContext:
    """Adapter presenting a supplier as the tax engine's selling party."""

    def __init__(self, supplier):
        self.state_code = supplier.state_code


class _BuyerTaxContext:
    """Adapter presenting our business profile as the tax engine's buyer."""

    def __init__(self, seller):
        self.state_code = seller.state_code if seller else None


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


def _resolve_lines(*, line_items, supplier, tax_mode):
    """Validate raw lines and compute their full financial breakdown.

    Every money value is rounded to paise here so exactly what is stored is
    what appears on the supplier bill check. Inventory only ever consumes
    the computed base_quantity and the per-base unit_cost_snapshot.
    """
    if not line_items:
        raise serializers.ValidationError(
            {"line_items": "At least one purchase line is required."}
        )

    seller = BusinessProfile.objects.first()
    calculated = []
    seen_products = set()
    for item in line_items:
        product = item["product"]
        if product.pk in seen_products:
            raise serializers.ValidationError(
                {"line_items": f"{product.name} appears more than once."}
            )
        seen_products.add(product.pk)

        quantity = Decimal(str(item["quantity"]))
        if quantity <= 0:
            raise serializers.ValidationError(
                {"line_items": f"Quantity for {product.name} must be positive."}
            )
        rate = Decimal(str(item.get("rate", 0) or 0))
        if rate < 0:
            raise serializers.ValidationError(
                {"line_items": f"Rate for {product.name} cannot be negative."}
            )
        discount_amount = Decimal(str(item.get("discount_amount", 0) or 0))
        if discount_amount < 0:
            raise serializers.ValidationError(
                {"line_items": f"Discount for {product.name} cannot be negative."}
            )
        gross = quantity * rate
        if discount_amount > gross:
            raise serializers.ValidationError(
                {"line_items": f"Discount for {product.name} exceeds the line gross."}
            )

        purchase_unit_name = str(item.get("purchase_unit_name") or PURCHASE_UNIT_PIECE).strip() or PURCHASE_UNIT_PIECE
        conversion_factor = Decimal(str(item.get("conversion_factor", 1) or 1))
        if conversion_factor <= 0:
            raise serializers.ValidationError(
                {"line_items": f"Conversion factor for {product.name} must be positive."}
            )
        if purchase_unit_name not in PURCHASE_UNIT_CHOICES:
            raise serializers.ValidationError(
                {
                    "line_items": (
                        f"Unknown purchase unit '{purchase_unit_name}' for {product.name}; "
                        f"use 'piece' or 'master box'."
                    )
                }
            )
        if purchase_unit_name == PURCHASE_UNIT_MASTER_BOX:
            master_box = _master_box_size(product)
            if master_box is None:
                raise serializers.ValidationError(
                    {
                        "line_items": (
                            f"{product.name} has no master box size; receive it in base units."
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

        product_tax_rate = product.tax.rate if product.tax else Decimal("0")
        submitted_tax_rate = item.get("tax_rate")
        if submitted_tax_rate is not None and Decimal(str(submitted_tax_rate)) != product_tax_rate:
            raise serializers.ValidationError(
                {
                    "line_items": (
                        f"Tax rate for {product.name} must match its configured GST rate "
                        f"of {product_tax_rate}%."
                    )
                }
            )

        calculated.append(
            {
                "product": product,
                "quantity": quantity,
                "purchase_unit_name": purchase_unit_name,
                "conversion_factor": conversion_factor,
                "base_quantity": base_quantity,
                "rate": _money(rate),
                "discount_amount": _money(discount_amount),
                "gross": _money(gross),
                "tax_rate": product_tax_rate,
            }
        )

    # Reuse the centralized GST engine with the parties correctly inverted
    # for a purchase: the supplier is the "seller" and our business is the
    # recipient. The engine compares the seller's state with the place of
    # supply (our state, where goods arrive), so an inter-state supplier
    # yields IGST exactly as the GST law treats the inbound supply.
    # Supplier bills quote tax to paise, so purchase rounding is round_paise.
    calc = calculate_gst(
        seller_profile=_SupplierTaxContext(supplier),
        customer=_BuyerTaxContext(seller),
        lines=[
            {
                "quantity": str(line["quantity"]),
                "rate_charged": str(line["rate"]),
                "discount_amount": str(line["discount_amount"]),
                "tax_rate": str(line["tax_rate"]),
            }
            for line in calculated
        ],
        place_of_supply_state_code=seller.state_code if seller else None,
        tax_mode=tax_mode,
        rounding=round_paise,
    )

    for line, engine_line in zip(calculated, calc["lines"]):
        line["taxable_value"] = engine_line["taxable_value"]
        line["cgst_rate"] = engine_line["cgst_rate"]
        line["cgst_amount"] = engine_line["cgst_amount"]
        line["sgst_rate"] = engine_line["sgst_rate"]
        line["sgst_amount"] = engine_line["sgst_amount"]
        line["igst_rate"] = engine_line["igst_rate"]
        line["igst_amount"] = engine_line["igst_amount"]
        line["line_total"] = engine_line["line_total"]
        # Inventory cost basis: pre-tax, post-discount, per base unit.
        line["unit_cost_snapshot"] = _money(line["taxable_value"] / line["base_quantity"])

    totals = calc["totals"]
    invoice_totals = {
        "subtotal": _money(totals["subtotal"]),
        "discount_total": _money(totals["discount_total"]),
        "taxable_total": _money(totals["taxable_value"]),
        "cgst_total": _money(totals["cgst_total"]),
        "sgst_total": _money(totals["sgst_total"]),
        "igst_total": _money(totals["igst_total"]),
        "total_amount": _money(totals["grand_total"]),
    }
    return calculated, invoice_totals


def _validate_supplier(*, supplier):
    supplier = Supplier.objects.get(pk=supplier.pk)
    if not supplier.is_active:
        raise serializers.ValidationError(
            {"supplier": "Inactive suppliers cannot receive purchases."}
        )
    return supplier


def _validate_warehouse(*, warehouse):
    if warehouse is None:
        return get_default_warehouse()
    return Warehouse.objects.get(pk=warehouse.pk)


def _persist_lines(*, purchase, calculated):
    for line in calculated:
        product = line["product"]
        PurchaseLineItem.objects.create(
            purchase_invoice=purchase,
            product=product,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku or "",
            hsn_sac_snapshot=product.hsn_sac,
            base_unit_snapshot=product.base_unit,
            quantity=line["quantity"],
            purchase_unit_name=line["purchase_unit_name"],
            conversion_factor=line["conversion_factor"],
            base_quantity=line["base_quantity"],
            rate=line["rate"],
            discount_amount=line["discount_amount"],
            tax_rate=line["tax_rate"],
            cgst_rate=line["cgst_rate"],
            cgst_amount=line["cgst_amount"],
            sgst_rate=line["sgst_rate"],
            sgst_amount=line["sgst_amount"],
            igst_rate=line["igst_rate"],
            igst_amount=line["igst_amount"],
            taxable_value=line["taxable_value"],
            line_total=line["line_total"],
            unit_cost_snapshot=line["unit_cost_snapshot"],
        )


def _snapshot_supplier(*, purchase, supplier):
    purchase.supplier_name_snapshot = supplier.name
    purchase.supplier_gstin_snapshot = supplier.gstin
    purchase.supplier_state_snapshot = supplier.state
    purchase.supplier_state_code_snapshot = supplier.state_code


@transaction.atomic
def create_purchase(
    *,
    supplier,
    warehouse,
    invoice_date,
    line_items,
    created_by,
    supplier_invoice_no="",
    tax_mode=PurchaseInvoice.TAX_MODE_EXCLUSIVE,
    notes="",
    post=False,
):
    """Create a purchase invoice as DRAFT, optionally posting it immediately."""
    supplier = _validate_supplier(supplier=supplier)
    warehouse = _validate_warehouse(warehouse=warehouse)
    calculated, totals = _resolve_lines(
        line_items=line_items, supplier=supplier, tax_mode=tax_mode
    )

    purchase = PurchaseInvoice(
        supplier=supplier,
        warehouse=warehouse,
        supplier_invoice_no=str(supplier_invoice_no or "").strip(),
        invoice_date=invoice_date,
        state=PurchaseInvoice.STATE_DRAFT,
        tax_mode=tax_mode,
        notes=notes or "",
        purchase_number=None,
        created_by=created_by,
        **totals,
    )
    _snapshot_supplier(purchase=purchase, supplier=supplier)
    purchase.save()

    _persist_lines(purchase=purchase, calculated=calculated)
    AuditLog.objects.create(
        user=created_by,
        action="purchase_created",
        entity_type="PurchaseInvoice",
        entity_id=purchase.pk,
        metadata={"supplier": supplier.name, "line_count": len(calculated)},
    )

    if post:
        purchase = post_purchase(purchase_id=purchase.pk, posted_by=created_by)
    return purchase


def _apply_weighted_average(*, balance, base_quantity, unit_cost):
    """Fold a receipt into the balance's weighted-average cost."""
    old_value = balance.quantity_on_hand * balance.average_cost
    new_value = base_quantity * unit_cost
    next_quantity = balance.quantity_on_hand + base_quantity
    if next_quantity <= 0:
        balance.average_cost = Decimal("0.00")
    else:
        balance.average_cost = (old_value + new_value) / next_quantity


def _reverse_weighted_average(*, balance, base_quantity, unit_cost):
    """Remove a receipt from the balance's weighted-average cost."""
    remaining = balance.quantity_on_hand - base_quantity
    if remaining <= 0:
        balance.average_cost = Decimal("0.00")
    else:
        remaining_value = balance.quantity_on_hand * balance.average_cost - base_quantity * unit_cost
        balance.average_cost = remaining_value / remaining


def _save_balance(*, balance, update_quantity, update_cost):
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")
    balance._allow_service_update = True
    fields = ["updated_at"]
    if update_quantity:
        fields.append("quantity_on_hand")
    if update_cost:
        fields.append("average_cost")
    balance.save(update_fields=fields)


def _resync_product_cache(*, product):
    total_stock = InventoryBalance.objects.filter(product=product).aggregate(
        total=models.Sum("quantity_on_hand")
    )["total"] or Decimal("0.000")
    product._allow_stock_cache_update = True
    product.current_stock = total_stock
    product.save(update_fields=["current_stock", "updated_at"])


@transaction.atomic
def post_purchase(*, purchase_id, posted_by):
    """Post a draft purchase: receive stock, update WAC, write the ledger."""
    purchase = PurchaseInvoice.objects.select_for_update().get(pk=purchase_id)
    if purchase.state == PurchaseInvoice.STATE_POSTED:
        return purchase  # idempotent replay
    if purchase.state != PurchaseInvoice.STATE_DRAFT:
        raise serializers.ValidationError(
            {"state": "Only draft purchases can be posted."}
        )

    lines = list(purchase.line_items.select_related("product", "product__tax"))
    if not lines:
        raise serializers.ValidationError({"line_items": "Nothing to receive."})

    products = Product.objects.select_for_update().in_bulk(
        {line.product_id for line in lines}
    )
    balances = {}
    for line in lines:
        product = products[line.product_id]
        balance = ensure_inventory_balance(
            product=product, warehouse=purchase.warehouse, created_by=posted_by
        )
        balances[product.pk] = InventoryBalance.objects.select_for_update().get(
            pk=balance.pk
        )

    purchase.purchase_number = next_purchase_number(purchase.invoice_date)
    purchase.state = PurchaseInvoice.STATE_POSTED
    purchase.posted_at = timezone.now()
    purchase._allow_lifecycle_transition = True
    # Financial totals were computed at draft time; nothing recomputes now.

    for line in lines:
        product = products[line.product_id]
        balance = balances[product.pk]
        base_quantity = line.base_quantity
        unit_cost = line.unit_cost_snapshot

        # Weighted average must fold the receipt into the PRE-receipt state,
        # so it is computed before the quantity update lands.
        _apply_weighted_average(
            balance=balance, base_quantity=base_quantity, unit_cost=unit_cost
        )
        balance.quantity_on_hand = balance.quantity_on_hand + base_quantity
        _save_balance(balance=balance, update_quantity=True, update_cost=True)

        StockLedger.objects.create(
            product=product,
            warehouse=purchase.warehouse,
            quantity_change=base_quantity,
            quantity_delta=base_quantity,
            movement_type=StockLedger.PURCHASE,
            reference_type="purchase_invoice",
            reference_id=purchase.pk,
            unit_cost=unit_cost,
            reason=f"Purchase {purchase.purchase_number}",
            created_by=posted_by,
        )

        _resync_product_cache(product=product)

    purchase.save(
        update_fields=["purchase_number", "state", "posted_at", "updated_at"]
    )
    AuditLog.objects.create(
        user=posted_by,
        action="purchase_posted",
        entity_type="PurchaseInvoice",
        entity_id=purchase.pk,
        metadata={
            "purchase_number": purchase.purchase_number,
            "warehouse": purchase.warehouse.code,
            "total_amount": str(purchase.total_amount),
        },
    )
    return purchase


@transaction.atomic
def cancel_purchase(*, purchase_id, cancelled_by, reason):
    """Cancel a posted purchase with compensating movements only."""
    reason = (reason or "").strip()
    if not reason:
        raise serializers.ValidationError(
            {"reason": "A cancellation reason is required."}
        )
    purchase = PurchaseInvoice.objects.select_for_update().get(pk=purchase_id)
    if purchase.state == PurchaseInvoice.STATE_CANCELLED:
        raise serializers.ValidationError(
            {"state": "Purchase is already cancelled."}
        )
    if purchase.state != PurchaseInvoice.STATE_POSTED:
        raise serializers.ValidationError(
            {"state": "Only posted purchases can be cancelled."}
        )

    lines = list(purchase.line_items.select_related("product"))
    products = Product.objects.select_for_update().in_bulk(
        {line.product_id for line in lines}
    )
    balances = {}
    for line in lines:
        product = products[line.product_id]
        try:
            balance = InventoryBalance.objects.get(
                product=product, warehouse=purchase.warehouse
            )
        except InventoryBalance.DoesNotExist:
            balance = InventoryBalance.objects.create(
                product=product,
                warehouse=purchase.warehouse,
                quantity_on_hand=Decimal("0.000"),
                average_cost=Decimal("0.00"),
            )
        balances[product.pk] = InventoryBalance.objects.select_for_update().get(
            pk=balance.pk
        )

    # Pre-check every reversal before applying any of them.
    for line in lines:
        balance = balances[line.product_id]
        if balance.quantity_on_hand < line.base_quantity:
            raise serializers.ValidationError(
                {
                    "state": (
                        f"Cannot cancel: {line.product_name_snapshot} stock in "
                        f"{purchase.warehouse.code} ({balance.quantity_on_hand}) is less than "
                        f"the received quantity ({line.base_quantity}). The goods may already "
                        "be sold; use a supplier return instead."
                    )
                }
            )

    for line in lines:
        product = products[line.product_id]
        balance = balances[product.pk]
        # The reverse fold needs the PRE-reversal quantity and average,
        # so it runs before the quantity update lands.
        _reverse_weighted_average(
            balance=balance,
            base_quantity=line.base_quantity,
            unit_cost=line.unit_cost_snapshot,
        )
        balance.quantity_on_hand = balance.quantity_on_hand - line.base_quantity
        _save_balance(balance=balance, update_quantity=True, update_cost=True)

        StockLedger.objects.create(
            product=product,
            warehouse=purchase.warehouse,
            quantity_change=-line.base_quantity,
            quantity_delta=-line.base_quantity,
            movement_type=StockLedger.PURCHASE_REVERSAL,
            reference_type="purchase_invoice_cancellation",
            reference_id=purchase.pk,
            unit_cost=line.unit_cost_snapshot,
            reason=reason,
            created_by=cancelled_by,
        )

        _resync_product_cache(product=product)

    purchase.state = PurchaseInvoice.STATE_CANCELLED
    purchase._allow_lifecycle_transition = True
    purchase.cancelled_at = timezone.now()
    purchase.cancelled_by = cancelled_by
    purchase.cancellation_reason = reason
    purchase.save(
        update_fields=[
            "state",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "updated_at",
        ]
    )
    AuditLog.objects.create(
        user=cancelled_by,
        action="purchase_cancelled",
        entity_type="PurchaseInvoice",
        entity_id=purchase.pk,
        metadata={"reason": reason, "purchase_number": purchase.purchase_number},
    )
    return purchase


@transaction.atomic
def update_purchase(*, purchase_id, updated_by, **fields):
    """Replace a draft purchase's editable content (header + lines)."""
    purchase = PurchaseInvoice.objects.select_for_update().get(pk=purchase_id)
    if purchase.state != PurchaseInvoice.STATE_DRAFT:
        raise serializers.ValidationError(
            {"state": "Only draft purchases can be edited."}
        )

    line_items = fields.get("line_items")
    supplier = fields.get("supplier")
    warehouse = fields.get("warehouse")
    invoice_date = fields.get("invoice_date")
    supplier_invoice_no = fields.get("supplier_invoice_no")
    tax_mode = fields.get("tax_mode")
    notes = fields.get("notes")

    if supplier is not None:
        purchase.supplier = _validate_supplier(supplier=supplier)
    if warehouse is not None:
        purchase.warehouse = _validate_warehouse(warehouse=warehouse)
    if invoice_date is not None:
        purchase.invoice_date = invoice_date
    if supplier_invoice_no is not None:
        purchase.supplier_invoice_no = str(supplier_invoice_no).strip()
    if tax_mode is not None:
        purchase.tax_mode = tax_mode
    if notes is not None:
        purchase.notes = notes

    if line_items is not None:
        calculated, totals = _resolve_lines(
            line_items=line_items,
            supplier=purchase.supplier,
            tax_mode=purchase.tax_mode,
        )
        for field, value in totals.items():
            setattr(purchase, field, value)
        _snapshot_supplier(purchase=purchase, supplier=purchase.supplier)
        purchase.line_items.all().delete()
        _persist_lines(purchase=purchase, calculated=calculated)
    else:
        # Supplier changed → refresh its snapshot; totals keep their basis.
        _snapshot_supplier(purchase=purchase, supplier=purchase.supplier)

    purchase.save()
    return purchase


@transaction.atomic
def delete_purchase(*, purchase_id):
    """Hard-delete a draft purchase. Posted history is never deleted."""
    purchase = PurchaseInvoice.objects.select_for_update().get(pk=purchase_id)
    if purchase.state != PurchaseInvoice.STATE_DRAFT:
        raise serializers.ValidationError(
            {"state": "Only draft purchases can be deleted."}
        )
    pk = purchase.pk
    purchase.delete()
    return pk
