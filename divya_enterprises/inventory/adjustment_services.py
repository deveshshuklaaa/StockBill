"""Stock Adjustment lifecycle: validation, atomic inventory mutation, WAC update, and ledger recording.

Strict rules:
- Base units (pieces) are authoritative.
- Master box quantity is converted using product's units_per_master_box dynamic attribute.
- STOCK_ADJUSTMENT_IN recalculates WAC using the weighted-average formula.
- STOCK_ADJUSTMENT_OUT snapshots current WAC and keeps average_cost unchanged.
- Negative resulting stock is strictly forbidden.
- Numbering is allocated inside the same atomic transaction so rolled-back adjustments never consume a serial.
- Immutability: adjustments, ledger rows, and audit logs are append-only.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection, models, transaction
from django.utils import timezone
from rest_framework import serializers

from billing.models import AuditLog

from .adjustment_numbering import next_adjustment_number
from .models import (
    InventoryBalance,
    Product,
    ProductAttributeValue,
    StockAdjustment,
    StockAdjustmentIdempotencyKey,
    StockLedger,
    Warehouse,
)
from .purchase_services import MASTER_BOX_ATTRIBUTE_CODE, _master_box_size
from .services import ensure_inventory_balance, get_default_warehouse


MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")


def _money(value):
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(str(value)).quantize(QUANTITY_QUANTUM)


def validate_adjustment_payload(
    *,
    product,
    warehouse,
    adjustment_type,
    quantity,
    unit,
    reason,
    effective_date,
    cost_per_piece=None,
    note="",
    conversion_factor=None,
):
    """Validate input parameters before performing row locking."""
    if not product:
        raise serializers.ValidationError({"product": "Product is required."})
    if not warehouse:
        raise serializers.ValidationError({"warehouse": "Warehouse is required."})

    if adjustment_type not in {
        StockAdjustment.ADJUSTMENT_TYPE_IN,
        StockAdjustment.ADJUSTMENT_TYPE_OUT,
    }:
        raise serializers.ValidationError(
            {
                "adjustment_type": f"Must be '{StockAdjustment.ADJUSTMENT_TYPE_IN}' or '{StockAdjustment.ADJUSTMENT_TYPE_OUT}'."
            }
        )

    # Unit & Conversion Factor
    normalized_unit = str(unit or StockAdjustment.UNIT_PIECE).strip().lower()
    if normalized_unit not in {StockAdjustment.UNIT_PIECE, StockAdjustment.UNIT_MASTER_BOX}:
        raise serializers.ValidationError(
            {"unit": f"Unknown unit '{unit}'; use 'piece' or 'master box'."}
        )

    if normalized_unit == StockAdjustment.UNIT_MASTER_BOX:
        master_box = _master_box_size(product)
        if master_box is None or master_box <= 0:
            raise serializers.ValidationError(
                {"unit": f"{product.name} has no master box size; adjust it in base units (piece)."}
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
                raise serializers.ValidationError({"conversion_factor": "Invalid conversion factor."})
    else:
        resolved_factor = Decimal(1)

    # Quantity
    try:
        qty = Decimal(str(quantity))
    except (ValueError, TypeError):
        raise serializers.ValidationError({"quantity": "A valid numeric quantity is required."})

    if qty <= 0:
        raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})

    base_quantity = _quantity(qty * resolved_factor)
    if base_quantity <= 0:
        raise serializers.ValidationError({"quantity": "Base quantity in pieces must be greater than zero."})

    # Effective Date
    if not effective_date:
        raise serializers.ValidationError({"effective_date": "Effective date is required."})
    if isinstance(effective_date, str):
        try:
            effective_date = date.fromisoformat(effective_date)
        except ValueError:
            raise serializers.ValidationError({"effective_date": "Date must use YYYY-MM-DD format."})

    if effective_date > date.today():
        raise serializers.ValidationError({"effective_date": "Effective date cannot be in the future."})

    # Reason & Note
    reason = str(reason or "").strip()
    if not reason:
        raise serializers.ValidationError({"reason": "Reason is required."})

    allowed_reasons = (
        StockAdjustment.REASONS_IN
        if adjustment_type == StockAdjustment.ADJUSTMENT_TYPE_IN
        else StockAdjustment.REASONS_OUT
    )
    if reason not in allowed_reasons:
        raise serializers.ValidationError(
            {
                "reason": f"Invalid reason '{reason}'. Allowed reasons for {adjustment_type}: {', '.join(allowed_reasons)}."
            }
        )

    note = str(note or "").strip()
    if reason == StockAdjustment.REASON_OTHER and not note:
        raise serializers.ValidationError({"note": "A note is required when reason is 'Other'."})

    # Costing check for IN
    if adjustment_type == StockAdjustment.ADJUSTMENT_TYPE_IN:
        if cost_per_piece is None or str(cost_per_piece).strip() == "":
            raise serializers.ValidationError(
                {"cost_per_piece": "Adjustment Cost (per Piece) is required for stock additions."}
            )
        try:
            cost = Decimal(str(cost_per_piece))
        except (ValueError, TypeError):
            raise serializers.ValidationError({"cost_per_piece": "Cost must be a valid number."})
        if cost < 0:
            raise serializers.ValidationError({"cost_per_piece": "Cost cannot be negative."})
    else:
        cost = None

    return {
        "product": product,
        "warehouse": warehouse,
        "adjustment_type": adjustment_type,
        "quantity": qty,
        "unit": normalized_unit,
        "conversion_factor": resolved_factor,
        "base_quantity": base_quantity,
        "effective_date": effective_date,
        "reason": reason,
        "note": note,
        "cost_per_piece": cost,
    }


@transaction.atomic
def post_stock_adjustment(
    *,
    product,
    warehouse,
    adjustment_type,
    quantity,
    unit,
    reason,
    effective_date,
    created_by,
    cost_per_piece=None,
    note="",
    conversion_factor=None,
    idempotency_key=None,
    request_hash="",
):
    """Execute a stock adjustment inside an atomic transaction with row locking."""
    validated = validate_adjustment_payload(
        product=product,
        warehouse=warehouse,
        adjustment_type=adjustment_type,
        quantity=quantity,
        unit=unit,
        reason=reason,
        effective_date=effective_date,
        cost_per_piece=cost_per_piece,
        note=note,
        conversion_factor=conversion_factor,
    )

    p_obj = validated["product"]
    w_obj = validated["warehouse"]
    base_qty = validated["base_quantity"]
    adj_type = validated["adjustment_type"]
    eff_date = validated["effective_date"]
    adj_reason = validated["reason"]
    adj_note = validated["note"]

    # 1. Ensure and row-lock InventoryBalance and Product
    ensure_inventory_balance(product=p_obj, warehouse=w_obj, created_by=created_by)
    balance = (
        InventoryBalance.objects.select_for_update()
        .get(product=p_obj, warehouse=w_obj)
    )
    locked_product = Product.objects.select_for_update().get(pk=p_obj.pk)

    current_qty = balance.quantity_on_hand
    current_wac = balance.average_cost

    if adj_type == StockAdjustment.ADJUSTMENT_TYPE_OUT:
        if current_qty < base_qty:
            raise serializers.ValidationError(
                {
                    "quantity": (
                        f"Insufficient stock for this adjustment. "
                        f"Available: {current_qty}, Requested: {base_qty}."
                    )
                }
            )
        cost_per_base_unit = current_wac
        adjustment_val = _money(base_qty * cost_per_base_unit)
        new_qty = _quantity(current_qty - base_qty)
        new_wac = current_wac  # Decreases do NOT change WAC
        ledger_qty_change = -base_qty
        movement_type = StockLedger.STOCK_ADJUSTMENT_OUT
    else:  # STOCK_ADJUSTMENT_IN
        cost_per_base_unit = _money(validated["cost_per_piece"])
        adjustment_val = _money(base_qty * cost_per_base_unit)
        new_qty = _quantity(current_qty + base_qty)
        if current_qty <= Decimal("0.000"):
            new_wac = cost_per_base_unit
        else:
            old_val = current_qty * current_wac
            incoming_val = base_qty * cost_per_base_unit
            new_wac = _money((old_val + incoming_val) / new_qty)
        ledger_qty_change = base_qty
        movement_type = StockLedger.STOCK_ADJUSTMENT_IN

    # 2. Update InventoryBalance with session guard
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")
    balance._allow_service_update = True
    balance.quantity_on_hand = new_qty
    balance.average_cost = new_wac
    balance.save(update_fields=["quantity_on_hand", "average_cost", "updated_at"])

    # 3. Resync Product.current_stock cache
    total_stock = (
        InventoryBalance.objects.filter(product=locked_product).aggregate(
            total=models.Sum("quantity_on_hand")
        )["total"]
        or Decimal("0.000")
    )
    locked_product._allow_stock_cache_update = True
    locked_product.current_stock = total_stock
    locked_product.save(update_fields=["current_stock", "updated_at"])

    # 4. Allocate gapless sequential adjustment number inside this transaction
    adj_number = next_adjustment_number(eff_date)

    # 5. Create StockAdjustment record
    adjustment = StockAdjustment.objects.create(
        adjustment_number=adj_number,
        product=locked_product,
        warehouse=w_obj,
        adjustment_type=adj_type,
        quantity=validated["quantity"],
        unit=validated["unit"],
        conversion_factor=validated["conversion_factor"],
        base_quantity=base_qty,
        cost_per_base_unit_snapshot=cost_per_base_unit,
        adjustment_value=adjustment_val,
        reason=adj_reason,
        note=adj_note,
        effective_date=eff_date,
        created_by=created_by,
    )

    # 6. Create StockLedger movement
    ledger_reason = f"{adj_reason}: {adj_note}".strip(": ")
    StockLedger.objects.create(
        product=locked_product,
        warehouse=w_obj,
        quantity_change=ledger_qty_change,
        quantity_delta=ledger_qty_change,
        movement_type=movement_type,
        reference=adj_number,
        reference_type="StockAdjustment",
        reference_id=adjustment.pk,
        unit_cost=cost_per_base_unit,
        reason=ledger_reason,
        created_by=created_by,
    )

    # 7. Create AuditLog
    AuditLog.objects.create(
        user=created_by,
        action="stock_adjustment_created",
        entity_type="StockAdjustment",
        entity_id=adjustment.pk,
        metadata={
            "adjustment_number": adj_number,
            "product_id": locked_product.pk,
            "product_name": locked_product.name,
            "warehouse_id": w_obj.pk,
            "warehouse_name": w_obj.name,
            "direction": adj_type,
            "quantity": str(validated["quantity"]),
            "unit": validated["unit"],
            "conversion_factor": str(validated["conversion_factor"]),
            "base_quantity": str(base_qty),
            "cost_per_base_unit": str(cost_per_base_unit),
            "adjustment_value": str(adjustment_val),
            "reason": adj_reason,
            "note": adj_note,
            "effective_date": str(eff_date),
            "previous_quantity": str(current_qty),
            "resulting_quantity": str(new_qty),
            "previous_wac": str(current_wac),
            "resulting_wac": str(new_wac),
        },
    )

    # 8. Store Idempotency Key if provided
    if idempotency_key:
        StockAdjustmentIdempotencyKey.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            adjustment=adjustment,
        )

    return adjustment
