from django.db import migrations, models


def backfill_base_quantity(apps, schema_editor):
    """Legacy lines billed in base units: quantity is the base quantity.

    The immutability trigger blocks updates to posted lines, so it is
    disabled for the duration of this historical backfill and re-enabled
    afterwards. The backfill only fills the new conversion columns from
    the existing quantity; no financial value changes.
    """
    from django.db.models.functions import Cast

    table = "billing_invoicelineitem"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        InvoiceLineItem = apps.get_model("billing", "InvoiceLineItem")
        InvoiceLineItem.objects.filter(base_quantity=0).update(
            base_quantity=Cast("quantity", models.DecimalField(max_digits=12, decimal_places=3))
        )
    finally:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0011_payment_payment_method_payment_reference_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoicelineitem",
            name="sales_unit_name",
            field=models.CharField(default="piece", max_length=50),
        ),
        migrations.AddField(
            model_name="invoicelineitem",
            name="conversion_factor",
            field=models.DecimalField(decimal_places=3, default=1, max_digits=12),
        ),
        migrations.AddField(
            model_name="invoicelineitem",
            name="base_quantity",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.RunPython(backfill_base_quantity, migrations.RunPython.noop),
    ]
