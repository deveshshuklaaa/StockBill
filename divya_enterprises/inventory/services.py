from decimal import Decimal

from django.db import connection, models, transaction
from rest_framework import serializers

from .models import InventoryBalance, Product, StockLedger, Warehouse


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
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")
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
    product._allow_stock_cache_update = True
    product.current_stock = total_stock
    product.save(update_fields=["current_stock", "updated_at"])
    return balance

