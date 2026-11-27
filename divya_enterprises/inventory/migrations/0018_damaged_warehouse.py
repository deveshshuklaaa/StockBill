"""Create the non-sellable "Damaged / Quarantine" holding warehouse.

Idempotent: get_or_create on the code, and an existing DAMAGED warehouse is
only marked non-sellable (its name and other fields are left alone).
Returned damaged goods are held here for 1:1 supplier replacement; they are
never written off and never billed from.
"""

from django.db import migrations

DAMAGED_CODE = "DAMAGED"
DAMAGED_NAME = "Damaged / Quarantine"


def create_damaged_warehouse(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    warehouse, created = Warehouse.objects.get_or_create(
        code=DAMAGED_CODE,
        defaults={"name": DAMAGED_NAME, "address": "", "is_sellable": False, "is_active": True},
    )
    if not created and warehouse.is_sellable:
        Warehouse.objects.filter(pk=warehouse.pk).update(is_sellable=False)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0017_warehouse_is_sellable_supplier_returns"),
    ]

    # Reversing leaves the warehouse in place: it may already hold stock.
    operations = [migrations.RunPython(create_damaged_warehouse, migrations.RunPython.noop)]
