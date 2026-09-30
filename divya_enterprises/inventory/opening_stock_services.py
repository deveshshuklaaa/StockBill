"""Opening Stock lifecycle: validation, atomic inventory initialization, initial WAC, and ledger recording.

Strict rules:
- Opening stock is NOT a purchase. It does NOT affect sales, purchases, suppliers, or customers.
- Base units (pieces) are authoritative.
- Master box quantity is converted using product's units_per_master_box dynamic attribute.
- Cost is ALWAYS per piece (base unit).
- Initial WAC = cost_per_piece, quantity_on_hand = base_quantity.
- Duplicate protection: only one opening-stock initialization per product+warehouse.
- Ambiguity rejection: reject opening stock if stock ledger activity or non-zero balance already exists for product+warehouse.
- Effective date cannot be in the future.
- Reason is required; if reason is 'Other', note is mandatory.
- Numbering is allocated inside the same atomic transaction so rolled-back attempts never consume a serial.
- Immutability: opening stock records, ledger rows, and audit logs are append-only.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection, models, transaction
from django.utils import timezone
from rest_framework import serializers

from billing.models import AuditLog

from .models import (
    InventoryBalance,
    OpeningStock,
    OpeningStockIdempotencyKey,
    Product,
    ProductAttributeValue,
    StockLedger,
    Warehouse,
)
from .opening_stock_numbering import next_opening_stock_number
from .purchase_services import MASTER_BOX_ATTRIBUTE_CODE, _master_box_size


MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")


def _money(value):
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(str(value)).quantize(QUANTITY_QUANTUM)


def validate_opening_stock_payload(
    *,
    product,
    warehouse,
    quantity,
    unit,
    cost_per_piece,
    reason,
    effective_date,
    note="",
    conversion_factor=None,
):
    """Validate opening stock inputs before performing row locking."""
    if not product:
        raise serializers.ValidationError({"product": "Product is required."})
    if not warehouse:
        raise serializers.ValidationError({"warehouse": "Warehouse is required."})

    if not product.is_active:
        raise serializers.ValidationError(
            {"product": f"Product '{product.name}' is inactive and cannot receive opening stock."}
        )
    if not warehouse.is_active:
        raise serializers.ValidationError(
            {"warehouse": f"Warehouse '{warehouse.name}' is inactive and cannot receive opening stock."}
        )

    # Unit & Conversion Factor
    normalized_unit = str(unit or OpeningStock.UNIT_PIECE).strip().lower()
    if normalized_unit not in {OpeningStock.UNIT_PIECE, OpeningStock.UNIT_MASTER_BOX}:
        raise serializers.ValidationError(
            {"unit": f"Unknown unit '{unit}'; use 'piece' or 'master box'."}
        )

    if normalized_unit == OpeningStock.UNIT_MASTER_BOX:
        master_box = _master_box_size(product)
        if master_box is None or master_box <= 0:
            raise serializers.ValidationError(
                {"unit": f"{product.name} has no master box size configured; initialize it in base units (piece)."}
            )
        resolved_factor = Decimal(master_box)
        if conversion_factor is not None:
            try:
                cf = Decimal(str(conversion_factor))
                if cf != resolved_factor:
                    raise serializers.ValidationError(
                        {
                            "conversion_factor": f"Master box conversion for {product.name} must be {master_box} (got {conversion_factor})."
                        }
                    )
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    {"conversion_factor": "Conversion factor must be numeric."}
                )
    else:
        resolved_factor = Decimal("1.000")
        if conversion_factor is not None:
            try:
                cf = Decimal(str(conversion_factor))
                if cf != Decimal("1"):
                    raise serializers.ValidationError(
                        {"conversion_factor": "Conversion factor for piece must be 1."}
                    )
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    {"conversion_factor": "Conversion factor must be numeric."}
                )

    # Quantity
    try:
        raw_qty = Decimal(str(quantity))
    except (ValueError, TypeError):
        raise serializers.ValidationError({"quantity": "Quantity must be numeric."})
    if raw_qty <= 0:
        raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})

    base_qty = _quantity(raw_qty * resolved_factor)
    if base_qty <= 0:
        raise serializers.ValidationError(
            {"quantity": "Resulting base quantity must be greater than zero."}
        )

    # Cost per piece (always per piece/base unit)
    if cost_per_piece is None:
        raise serializers.ValidationError({"cost_per_piece": "Cost per piece is required."})
    try:
        resolved_cost = Decimal(str(cost_per_piece))
    except (ValueError, TypeError):
        raise serializers.ValidationError({"cost_per_piece": "Cost per piece must be numeric."})
    if resolved_cost < 0:
        raise serializers.ValidationError(
            {"cost_per_piece": "Cost per piece cannot be negative."}
        )
    resolved_cost = _money(resolved_cost)

    # Opening Value
    opening_val = _money(base_qty * resolved_cost)

    # Effective Date
    if not effective_date:
        raise serializers.ValidationError({"effective_date": "Effective date is required."})
    if isinstance(effective_date, str):
        try:
            effective_date = date.fromisoformat(effective_date)
        except ValueError:
            raise serializers.ValidationError(
                {"effective_date": "Effective date must be YYYY-MM-DD."}
            )
    today = timezone.localdate()
    if effective_date > today:
        raise serializers.ValidationError(
            {"effective_date": "Effective date cannot be in the future."}
        )

    # Reason & Note
    if not reason or not str(reason).strip():
        raise serializers.ValidationError({"reason": "Reason is required."})
    reason = str(reason).strip()
    note = str(note or "").strip()
    if reason == OpeningStock.REASON_OTHER and not note:
        raise serializers.ValidationError(
            {"note": "Note is mandatory when reason is 'Other'."}
        )

    # Duplicate & Existing Activity Checks
    if OpeningStock.objects.filter(product=product, warehouse=warehouse).exists():
        raise serializers.ValidationError(
            {
                "product": (
                    f"Opening stock already initialized for {product.name} at {warehouse.name}. "
                    "Use Stock Adjustment for subsequent inventory changes."
                )
            }
        )

    existing_ledger = StockLedger.objects.filter(product=product, warehouse=warehouse).exists()
    if existing_ledger:
        raise serializers.ValidationError(
            {
                "product": (
                    f"Cannot initialize opening stock: {product.name} already has stock ledger movements at {warehouse.name}. "
                    "Opening stock is only permitted before inventory activity begins. Use Stock Adjustment instead."
                )
            }
        )

    balance_exists = InventoryBalance.objects.filter(
        product=product, warehouse=warehouse, quantity_on_hand__gt=0
    ).exists()
    if balance_exists:
        raise serializers.ValidationError(
            {
                "product": (
                    f"Cannot initialize opening stock: {product.name} already has an active inventory balance at {warehouse.name}. "
                    "Use Stock Adjustment instead."
                )
            }
        )

    return {
        "unit": normalized_unit,
        "conversion_factor": resolved_factor,
        "base_quantity": base_qty,
        "cost_per_piece": resolved_cost,
        "opening_value": opening_val,
        "effective_date": effective_date,
        "reason": reason,
        "note": note,
    }


@transaction.atomic
def create_opening_stock(
    *,
    product=None,
    product_id=None,
    warehouse=None,
    warehouse_id=None,
    quantity,
    unit,
    cost_per_piece,
    reason,
    effective_date,
    note="",
    conversion_factor=None,
    created_by=None,
    idempotency_key=None,
    request_hash="",
):
    """Atomically record opening stock, update balance, and log to ledger and audit."""
    if product is not None:
        product_id = product.pk if hasattr(product, "pk") else product
    if warehouse is not None:
        warehouse_id = warehouse.pk if hasattr(warehouse, "pk") else warehouse
    if idempotency_key:
        existing = OpeningStockIdempotencyKey.objects.filter(key=idempotency_key).select_related("opening_stock").first()
        if existing:
            if existing.request_hash and existing.request_hash != request_hash:
                raise serializers.ValidationError(
                    {"idempotency_key": "Idempotency key has already been used with different request parameters."}
                )
            return existing.opening_stock

    try:
        product = Product.objects.select_for_update().get(pk=product_id)
    except Product.DoesNotExist:
        raise serializers.ValidationError({"product": "Product does not exist."})

    try:
        warehouse = Warehouse.objects.select_for_update().get(pk=warehouse_id)
    except Warehouse.DoesNotExist:
        raise serializers.ValidationError({"warehouse": "Warehouse does not exist."})

    validated = validate_opening_stock_payload(
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit=unit,
        cost_per_piece=cost_per_piece,
        reason=reason,
        effective_date=effective_date,
        note=note,
        conversion_factor=conversion_factor,
    )

    opening_stock_number = next_opening_stock_number(validated["effective_date"])

    opening_stock = OpeningStock.objects.create(
        opening_stock_number=opening_stock_number,
        product=product,
        warehouse=warehouse,
        quantity=Decimal(str(quantity)),
        unit=validated["unit"],
        conversion_factor=validated["conversion_factor"],
        base_quantity=validated["base_quantity"],
        cost_per_piece=validated["cost_per_piece"],
        opening_value=validated["opening_value"],
        reason=validated["reason"],
        note=validated["note"],
        effective_date=validated["effective_date"],
        created_by=created_by,
    )

    if idempotency_key:
        OpeningStockIdempotencyKey.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            opening_stock=opening_stock,
        )

    # Initialize InventoryBalance
    balance, _ = InventoryBalance.objects.get_or_create(
        product=product,
        warehouse=warehouse,
        defaults={
            "quantity_on_hand": Decimal("0.000"),
            "average_cost": Decimal("0.00"),
        },
    )
    balance = InventoryBalance.objects.select_for_update().get(pk=balance.pk)
    balance.quantity_on_hand = validated["base_quantity"]
    balance.average_cost = validated["cost_per_piece"]

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")
    balance._allow_service_update = True
    balance.save(update_fields=["quantity_on_hand", "average_cost", "updated_at"])

    # Synchronize product-level current_stock cache and cost_price fallback
    total_stock = (
        InventoryBalance.objects.filter(product=product).aggregate(
            total=models.Sum("quantity_on_hand")
        )["total"]
        or Decimal("0.000")
    )
    product._allow_stock_cache_update = True
    product.current_stock = total_stock
    if product.cost_price == Decimal("0.00"):
        product.cost_price = validated["cost_per_piece"]
        product.save(update_fields=["current_stock", "cost_price", "updated_at"])
    else:
        product.save(update_fields=["current_stock", "updated_at"])

    # StockLedger immutable movement
    StockLedger.objects.create(
        product=product,
        warehouse=warehouse,
        quantity_change=validated["base_quantity"],
        quantity_delta=validated["base_quantity"],
        movement_type=StockLedger.OPENING_STOCK,
        reference=opening_stock.opening_stock_number,
        reference_type="opening_stock",
        reference_id=opening_stock.pk,
        unit_cost=validated["cost_per_piece"],
        reason=f"Opening stock: {validated['reason']}",
        created_by=created_by,
    )

    AuditLog.objects.create(
        user=created_by,
        action="opening_stock_created",
        entity_type="OpeningStock",
        entity_id=opening_stock.pk,
        metadata={
            "opening_stock_number": opening_stock.opening_stock_number,
            "product_id": product.pk,
            "warehouse_id": warehouse.pk,
            "base_quantity": str(validated["base_quantity"]),
            "cost_per_piece": str(validated["cost_per_piece"]),
            "opening_value": str(validated["opening_value"]),
            "reason": validated["reason"],
            "effective_date": validated["effective_date"].isoformat(),
        },
    )

    return opening_stock
