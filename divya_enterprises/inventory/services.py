from decimal import Decimal

from django.db import models, transaction
from rest_framework import serializers

from .models import InventoryBalance, Product, PurchaseInvoice, PurchaseLineItem, StockLedger, Warehouse


DEFAULT_WAREHOUSE_CODE = "MAIN"


def get_default_warehouse():
    warehouse, _ = Warehouse.objects.get_or_create(
        code=DEFAULT_WAREHOUSE_CODE,
        defaults={"name": "Main Warehouse", "address": ""},
    )
    return warehouse


def ensure_inventory_balance(*, product, warehouse=None, created_by=None):
    warehouse = warehouse or get_default_warehouse()
    balance, created = InventoryBalance.objects.get_or_create(
        product=product,
        warehouse=warehouse,
        defaults={
            "quantity_on_hand": product.current_stock or Decimal("0.000"),
            "average_cost": product.cost_price or Decimal("0.00"),
        },
    )
    if created and product.current_stock:
        StockLedger.objects.create(
            product=product,
            warehouse=warehouse,
            quantity_change=product.current_stock,
            quantity_delta=product.current_stock,
            movement_type=StockLedger.OPENING_STOCK,
            reference_type="legacy_product_stock",
            reference_id=product.pk,
            reason="Compatibility bootstrap from Product.current_stock",
            created_by=created_by,
        )
    return balance


@transaction.atomic
def adjust_inventory(*, product, quantity_delta, movement_type, created_by=None, reference_type="", reference_id=None, unit_cost=None, reason="", warehouse=None):
    """Apply one base-unit inventory movement and its matching audit event atomically."""
    warehouse = warehouse or get_default_warehouse()
    delta = Decimal(quantity_delta)
    if delta == 0:
        raise serializers.ValidationError({"quantity": "Inventory movement cannot be zero."})

    balance = ensure_inventory_balance(product=product, warehouse=warehouse, created_by=created_by)
    balance = InventoryBalance.objects.select_for_update().get(pk=balance.pk)
    next_quantity = balance.quantity_on_hand + delta
    if next_quantity < 0:
        raise serializers.ValidationError(
            {"quantity": f"Insufficient stock for {product.name}. Available: {balance.quantity_on_hand}."}
        )
    balance.quantity_on_hand = next_quantity
    balance._allow_service_update = True
    balance.save(update_fields=["quantity_on_hand", "updated_at"])

    StockLedger.objects.create(
        product=product,
        warehouse=warehouse,
        quantity_change=delta,
        quantity_delta=delta,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=reference_id,
        unit_cost=unit_cost,
        reason=reason,
        created_by=created_by,
    )

    # Keep the legacy global cache synchronized until all consumers migrate to balances.
    total_stock = InventoryBalance.objects.filter(product=product).aggregate(total=models.Sum("quantity_on_hand"))["total"] or Decimal("0.000")
    Product.objects.filter(pk=product.pk).update(current_stock=total_stock)
    product.current_stock = total_stock
    return balance


@transaction.atomic
def receive_purchase(*, supplier, warehouse, invoice_number, invoice_date, created_by, line_items):
    if not line_items:
        raise serializers.ValidationError({"line_items": "At least one purchase line is required."})
    products = Product.objects.select_for_update().in_bulk({item["product"].pk for item in line_items})
    balances = {}
    calculated = []
    total = Decimal("0.00")
    for item in line_items:
        product = products[item["product"].pk]
        quantity = Decimal(item["quantity"])
        unit_cost = Decimal(item["unit_cost"])
        if quantity <= 0 or unit_cost < 0:
            raise serializers.ValidationError({"line_items": "Purchase quantity must be positive and cost cannot be negative."})
        balance = ensure_inventory_balance(product=product, warehouse=warehouse, created_by=created_by)
        balances[product.pk] = InventoryBalance.objects.select_for_update().get(pk=balance.pk)
        line_total = quantity * unit_cost
        calculated.append((product, quantity, unit_cost, line_total))
        total += line_total

    purchase = PurchaseInvoice.objects.create(
        supplier=supplier,
        warehouse=warehouse,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        total_amount=total,
        created_by=created_by,
    )
    for product, quantity, unit_cost, line_total in calculated:
        balance = balances[product.pk]
        old_value = balance.quantity_on_hand * balance.average_cost
        new_value = quantity * unit_cost
        next_quantity = balance.quantity_on_hand + quantity
        balance.average_cost = (old_value + new_value) / next_quantity if next_quantity else Decimal("0.00")
        balance._allow_service_update = True
        balance.save(update_fields=["average_cost", "updated_at"])
        PurchaseLineItem.objects.create(
            purchase_invoice=purchase,
            product=product,
            quantity=quantity,
            unit_cost=unit_cost,
            line_total=line_total,
        )
        adjust_inventory(
            product=product,
            warehouse=warehouse,
            quantity_delta=quantity,
            movement_type=StockLedger.PURCHASE,
            created_by=created_by,
            reference_type="purchase_invoice",
            reference_id=purchase.pk,
            unit_cost=unit_cost,
        )
        product._allow_stock_cache_update = True
        product.cost_price = unit_cost
        product.save(update_fields=["cost_price", "updated_at"])
    return purchase
