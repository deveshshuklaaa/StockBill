"""Warehouse Transfer service: atomic stock transfer between warehouses with WAC tracking.

Strict rules:
- Base units (pieces) are authoritative.
- Master box quantity is converted using product's units_per_master_box dynamic attribute.
- Source and destination warehouses must be different and active.
- Product must be active.
- Source warehouse WAC remains unchanged.
- Destination warehouse WAC is recalculated using weighted-average cost formula.
- Total company inventory valuation remains unchanged.
- Exactly two StockLedger movements: WAREHOUSE_TRANSFER_OUT and WAREHOUSE_TRANSFER_IN.
- Deadlock-free row locking by ordering warehouse IDs.
- Numbering is allocated inside the same atomic transaction.
- Immutability: transfers and ledger rows are append-only.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection, models, transaction
from rest_framework import serializers

from billing.models import AuditLog

from .models import (
    InventoryBalance,
    Product,
    StockLedger,
    Warehouse,
    WarehouseTransfer,
    WarehouseTransferIdempotencyKey,
)
from .purchase_services import _master_box_size
from .services import ensure_inventory_balance
from .transfer_numbering import next_transfer_number


MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")


def _money(value):
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _quantity(value):
    return Decimal(str(value)).quantize(QUANTITY_QUANTUM)


def validate_transfer_payload(
    *,
    product,
    source_warehouse,
    destination_warehouse,
    quantity,
    unit,
    reason,
    effective_date,
    note="",
    conversion_factor=None,
):
    """Validate input parameters before acquiring locks."""
    if not product:
        raise serializers.ValidationError({"product": "Product is required."})
    if not getattr(product, "is_active", True):
        raise serializers.ValidationError({"product": "Product must be active."})

    if not source_warehouse:
        raise serializers.ValidationError({"source_warehouse": "Source warehouse is required."})
    if not destination_warehouse:
        raise serializers.ValidationError({"destination_warehouse": "Destination warehouse is required."})

    if source_warehouse.pk == destination_warehouse.pk:
        raise serializers.ValidationError(
            {"destination_warehouse": "Source and destination warehouses must be different."}
        )

    if not getattr(source_warehouse, "is_active", True):
        raise serializers.ValidationError(
            {"source_warehouse": "Source warehouse must be active for a new transfer."}
        )
    if not getattr(destination_warehouse, "is_active", True):
        raise serializers.ValidationError(
            {"destination_warehouse": "Destination warehouse must be active for a new transfer."}
        )

    # Unit & Conversion Factor
    normalized_unit = str(unit or WarehouseTransfer.UNIT_PIECE).strip().lower()
    if normalized_unit not in {WarehouseTransfer.UNIT_PIECE, WarehouseTransfer.UNIT_MASTER_BOX}:
        raise serializers.ValidationError(
            {"unit": f"Unknown unit '{unit}'; use 'piece' or 'master box'."}
        )

    if normalized_unit == WarehouseTransfer.UNIT_MASTER_BOX:
        master_box = _master_box_size(product)
        if master_box is None or master_box <= 0:
            raise serializers.ValidationError(
                {"unit": f"{product.name} has no master box size; transfer it in base units (piece)."}
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

    note = str(note or "").strip()
    if reason == WarehouseTransfer.REASON_OTHER and not note:
        raise serializers.ValidationError({"note": "A note is required when reason is 'Other'."})

    return {
        "product": product,
        "source_warehouse": source_warehouse,
        "destination_warehouse": destination_warehouse,
        "quantity": qty,
        "unit": normalized_unit,
        "conversion_factor": resolved_factor,
        "base_quantity": base_quantity,
        "effective_date": effective_date,
        "reason": reason,
        "note": note,
    }


@transaction.atomic
def post_warehouse_transfer(
    *,
    product,
    source_warehouse,
    destination_warehouse,
    quantity,
    unit,
    reason,
    effective_date,
    created_by,
    note="",
    conversion_factor=None,
    idempotency_key=None,
    request_hash="",
):
    """Execute a warehouse stock transfer atomically with safe ordered locking."""
    validated = validate_transfer_payload(
        product=product,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        quantity=quantity,
        unit=unit,
        reason=reason,
        effective_date=effective_date,
        note=note,
        conversion_factor=conversion_factor,
    )

    p_obj = validated["product"]
    src_wh = validated["source_warehouse"]
    dst_wh = validated["destination_warehouse"]
    base_qty = validated["base_quantity"]
    eff_date = validated["effective_date"]
    transfer_reason = validated["reason"]
    transfer_note = validated["note"]

    # 1. Order warehouses to prevent deadlocks
    ordered_warehouses = sorted([src_wh, dst_wh], key=lambda w: w.pk)
    for wh in ordered_warehouses:
        ensure_inventory_balance(product=p_obj, warehouse=wh, created_by=created_by)

    # 2. Lock balances and product
    locked_balances = {
        wh.pk: InventoryBalance.objects.select_for_update().get(product=p_obj, warehouse=wh)
        for wh in ordered_warehouses
    }
    locked_product = Product.objects.select_for_update().get(pk=p_obj.pk)

    source_balance = locked_balances[src_wh.pk]
    dest_balance = locked_balances[dst_wh.pk]

    src_qty = source_balance.quantity_on_hand
    src_wac = source_balance.average_cost

    # 3. Source availability check
    if src_qty < base_qty:
        raise serializers.ValidationError(
            {
                "quantity": (
                    f"Insufficient stock in source warehouse '{src_wh.name}'. "
                    f"Available: {src_qty}, Requested: {base_qty}."
                )
            }
        )

    # 4. Cost snapshot from source
    unit_cost_snapshot = src_wac
    transfer_value = _money(base_qty * unit_cost_snapshot)

    # 5. New source state
    new_src_qty = _quantity(src_qty - base_qty)
    new_src_wac = src_wac  # Decreases do not change source WAC

    # 6. New destination state & WAC
    dst_qty = dest_balance.quantity_on_hand
    dst_wac = dest_balance.average_cost
    new_dst_qty = _quantity(dst_qty + base_qty)

    if dst_qty <= Decimal("0.000"):
        new_dst_wac = unit_cost_snapshot
    else:
        existing_val = dst_qty * dst_wac
        incoming_val = base_qty * unit_cost_snapshot
        new_dst_wac = _money((existing_val + incoming_val) / new_dst_qty)

    # 7. Mutate inventory balances with DB session guard
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")

    source_balance._allow_service_update = True
    source_balance.quantity_on_hand = new_src_qty
    source_balance.average_cost = new_src_wac
    source_balance.save(update_fields=["quantity_on_hand", "average_cost", "updated_at"])

    dest_balance._allow_service_update = True
    dest_balance.quantity_on_hand = new_dst_qty
    dest_balance.average_cost = new_dst_wac
    dest_balance.save(update_fields=["quantity_on_hand", "average_cost", "updated_at"])

    # 8. Product cached stock
    total_stock = (
        InventoryBalance.objects.filter(product=locked_product).aggregate(
            total=models.Sum("quantity_on_hand")
        )["total"]
        or Decimal("0.000")
    )
    locked_product._allow_stock_cache_update = True
    locked_product.current_stock = total_stock
    locked_product.save(update_fields=["current_stock", "updated_at"])

    # 9. Allocate sequential transfer number inside this transaction
    trf_number = next_transfer_number(eff_date)

    # 10. Create WarehouseTransfer record
    transfer = WarehouseTransfer.objects.create(
        transfer_number=trf_number,
        product=locked_product,
        source_warehouse=src_wh,
        destination_warehouse=dst_wh,
        quantity=validated["quantity"],
        unit=validated["unit"],
        conversion_factor=validated["conversion_factor"],
        base_quantity=base_qty,
        unit_cost_snapshot=unit_cost_snapshot,
        transfer_value=transfer_value,
        reason=transfer_reason,
        note=transfer_note,
        effective_date=eff_date,
        created_by=created_by,
    )

    # 11. Create TWO StockLedger movements
    ledger_note = f"{transfer_reason}: {transfer_note}".strip(": ")

    # Source: WAREHOUSE_TRANSFER_OUT
    StockLedger.objects.create(
        product=locked_product,
        warehouse=src_wh,
        quantity_change=-base_qty,
        quantity_delta=-base_qty,
        movement_type=StockLedger.WAREHOUSE_TRANSFER_OUT,
        reference=trf_number,
        reference_type="WarehouseTransfer",
        reference_id=transfer.pk,
        unit_cost=unit_cost_snapshot,
        reason=f"Transfer to {dst_wh.name} - {ledger_note}".strip(" -"),
        created_by=created_by,
    )

    # Destination: WAREHOUSE_TRANSFER_IN
    StockLedger.objects.create(
        product=locked_product,
        warehouse=dst_wh,
        quantity_change=base_qty,
        quantity_delta=base_qty,
        movement_type=StockLedger.WAREHOUSE_TRANSFER_IN,
        reference=trf_number,
        reference_type="WarehouseTransfer",
        reference_id=transfer.pk,
        unit_cost=unit_cost_snapshot,
        reason=f"Transfer from {src_wh.name} - {ledger_note}".strip(" -"),
        created_by=created_by,
    )

    # 12. AuditLog
    AuditLog.objects.create(
        user=created_by,
        action="warehouse_transfer_created",
        entity_type="WarehouseTransfer",
        entity_id=transfer.pk,
        metadata={
            "transfer_number": trf_number,
            "source_warehouse_id": src_wh.pk,
            "source_warehouse_name": src_wh.name,
            "destination_warehouse_id": dst_wh.pk,
            "destination_warehouse_name": dst_wh.name,
            "product_id": locked_product.pk,
            "product_name": locked_product.name,
            "quantity": str(validated["quantity"]),
            "unit": validated["unit"],
            "conversion_factor": str(validated["conversion_factor"]),
            "base_quantity": str(base_qty),
            "unit_cost_snapshot": str(unit_cost_snapshot),
            "transfer_value": str(transfer_value),
            "reason": transfer_reason,
            "note": transfer_note,
            "effective_date": str(eff_date),
            "source_previous_quantity": str(src_qty),
            "source_resulting_quantity": str(new_src_qty),
            "source_wac": str(src_wac),
            "destination_previous_quantity": str(dst_qty),
            "destination_resulting_quantity": str(new_dst_qty),
            "destination_previous_wac": str(dst_wac),
            "destination_resulting_wac": str(new_dst_wac),
        },
    )

    # 13. Idempotency Key
    if idempotency_key:
        WarehouseTransferIdempotencyKey.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            transfer=transfer,
        )

    return transfer
