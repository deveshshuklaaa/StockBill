"""Damaged goods back to the supplier for 1:1 replacement (minimal exit leg).

No purchase-return / debit-note workflow existed (billing.DebitNote is a
customer-side document), so this is deliberately small:

1. return_to_supplier(): base units leave a warehouse (default Damaged /
   Quarantine) with a PURCHASE_RETURN stock movement and an append-only
   SupplierReturn record valued at quantity x unit_cost.
2. receive_replacement(): replacement goods arrive against that return
   (default into Main) with a PURCHASE movement referencing
   "supplier_replacement", valued at the return's unit cost.

On the supplier ledger the return is a debit and the replacement a credit of
the same value, so a full 1:1 replacement nets to zero. Neither leg changes
the weighted-average cost: like sales returns, both go through
adjust_inventory(), which moves quantity only.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from billing.models import AuditLog

from .models import InventoryBalance, PurchaseLineItem, PurchaseInvoice, StockLedger, SupplierReplacementReceipt, SupplierReturn, Warehouse
from .services import adjust_inventory, get_damaged_warehouse, get_default_warehouse

MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(str(value)).quantize(QUANTITY_QUANTUM)


def default_return_unit_cost(*, supplier, product):
    """Valuation basis when none is entered.

    The pre-tax unit cost of the latest posted purchase of this product from
    this supplier; else the product's Main-warehouse average cost; else its
    catalogue cost price.
    """
    last_line = (
        PurchaseLineItem.objects.filter(
            product=product,
            purchase_invoice__supplier=supplier,
            purchase_invoice__state=PurchaseInvoice.STATE_POSTED,
        )
        .order_by("-purchase_invoice__invoice_date", "-purchase_invoice_id")
        .first()
    )
    if last_line is not None:
        return last_line.unit_cost_snapshot
    balance = InventoryBalance.objects.filter(product=product, warehouse=get_default_warehouse()).first()
    if balance is not None and balance.average_cost > 0:
        return _money(balance.average_cost)
    return _money(product.cost_price or 0)


def _active_warehouse(warehouse, field):
    warehouse = Warehouse.objects.get(pk=warehouse.pk)
    if not warehouse.is_active:
        raise serializers.ValidationError({field: f"Warehouse {warehouse.code} is inactive."})
    return warehouse


@transaction.atomic
def return_to_supplier(*, supplier, product, quantity, created_by, warehouse=None, unit_cost=None, return_date=None, reference="", notes=""):
    if not supplier.is_active:
        raise serializers.ValidationError({"supplier": "Inactive suppliers cannot take returns."})
    quantity = _quantity(quantity)
    if quantity <= 0:
        raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
    warehouse = _active_warehouse(warehouse or get_damaged_warehouse(), "warehouse")
    if unit_cost is None or str(unit_cost).strip() == "":
        unit_cost = default_return_unit_cost(supplier=supplier, product=product)
    unit_cost = _money(unit_cost)
    if unit_cost < 0:
        raise serializers.ValidationError({"unit_cost": "Unit cost cannot be negative."})

    supplier_return = SupplierReturn.objects.create(
        supplier=supplier,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_cost=unit_cost,
        value=_money(quantity * unit_cost),
        return_date=return_date or timezone.localdate(),
        reference=(reference or "").strip(),
        notes=notes or "",
        created_by=created_by,
    )
    # Raises (and rolls the record back) if the warehouse lacks the stock.
    adjust_inventory(
        product=product,
        quantity_delta=-quantity,
        movement_type=StockLedger.PURCHASE_RETURN,
        created_by=created_by,
        reference_type="supplier_return",
        reference_id=supplier_return.pk,
        unit_cost=unit_cost,
        reason=f"{supplier_return.display_number} to {supplier.name} for replacement",
        warehouse=warehouse,
    )
    AuditLog.objects.create(
        user=created_by, action="supplier_return_created", entity_type="SupplierReturn", entity_id=supplier_return.pk,
        metadata={"supplier_id": supplier.pk, "product_id": product.pk, "quantity": str(quantity), "warehouse": warehouse.code},
    )
    return supplier_return


def replaced_quantity(supplier_return):
    return supplier_return.replacements.aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")


@transaction.atomic
def receive_replacement(*, supplier_return, quantity, created_by, warehouse=None, receipt_date=None, reference="", notes=""):
    supplier_return = SupplierReturn.objects.select_for_update().select_related("supplier", "product").get(pk=supplier_return.pk)
    quantity = _quantity(quantity)
    if quantity <= 0:
        raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
    outstanding = supplier_return.quantity - replaced_quantity(supplier_return)
    if quantity > outstanding:
        raise serializers.ValidationError(
            {"quantity": f"Only {outstanding.normalize():f} of {supplier_return.display_number} is still awaiting replacement."}
        )
    warehouse = _active_warehouse(warehouse or get_default_warehouse(), "warehouse")
    receipt = SupplierReplacementReceipt.objects.create(
        supplier_return=supplier_return,
        warehouse=warehouse,
        quantity=quantity,
        value=_money(quantity * supplier_return.unit_cost),
        receipt_date=receipt_date or timezone.localdate(),
        reference=(reference or "").strip(),
        notes=notes or "",
        created_by=created_by,
    )
    adjust_inventory(
        product=supplier_return.product,
        quantity_delta=quantity,
        movement_type=StockLedger.PURCHASE,
        created_by=created_by,
        reference_type="supplier_replacement",
        reference_id=receipt.pk,
        unit_cost=supplier_return.unit_cost,
        reason=f"Replacement for {supplier_return.display_number} from {supplier_return.supplier.name}",
        warehouse=warehouse,
    )
    AuditLog.objects.create(
        user=created_by, action="supplier_replacement_received", entity_type="SupplierReturn", entity_id=supplier_return.pk,
        metadata={"receipt_id": receipt.pk, "quantity": str(quantity), "warehouse": warehouse.code},
    )
    return receipt
