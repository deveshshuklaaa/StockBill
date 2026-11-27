"""Database-level append-only guard for supplier payments and reversals.

Reuses stockbill_protect_supplier_ledger() from 0019 (it rejects every
UPDATE and DELETE), matching the protection billing_payment and
billing_paymentreversal get from stockbill_protect_history().
"""

from django.db import migrations

TABLES = [
    "inventory_supplierpayment",
    "inventory_supplierpaymentreversal",
]


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER stockbill_protect_{table} "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION stockbill_protect_supplier_ledger();"
        )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS stockbill_protect_{table} ON {table};")


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0020_supplier_payments"),
    ]

    operations = [migrations.RunPython(install, uninstall)]
