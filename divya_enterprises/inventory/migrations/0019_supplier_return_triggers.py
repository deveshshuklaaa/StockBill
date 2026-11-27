"""Database-level append-only guard for supplier returns and replacements.

A separate trigger function (stockbill_protect_supplier_ledger) rather than
another branch in stockbill_protect_history(): the shared function is
redefined wholesale by several migrations, and keeping these tables apart
avoids having to restate (and possibly drift) its full body here.
"""

from django.db import migrations

TABLES = [
    "inventory_supplierreturn",
    "inventory_supplierreplacementreceipt",
]

TRIGGER_FUNCTION = r'''
CREATE OR REPLACE FUNCTION stockbill_protect_supplier_ledger() RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
'''


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(TRIGGER_FUNCTION)
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
    schema_editor.execute("DROP FUNCTION IF EXISTS stockbill_protect_supplier_ledger();")


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0018_damaged_warehouse"),
    ]

    operations = [migrations.RunPython(install, uninstall)]
