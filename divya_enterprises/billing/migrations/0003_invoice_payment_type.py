from django.db import migrations, models


def backfill_payment_type(apps, schema_editor):
    Invoice = apps.get_model("billing", "Invoice")
    Payment = apps.get_model("billing", "Payment")
    cash_invoice_ids = Payment.objects.filter(invoice_id__isnull=False).values_list("invoice_id", flat=True)
    Invoice.objects.filter(pk__in=cash_invoice_ids).update(payment_type="cash")
    # One-time historical backfill: invoices without a payment are treated as credit.


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_transactional_billing_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="payment_type",
            field=models.CharField(
                choices=[("cash", "Cash"), ("credit", "Credit")],
                default="credit",
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill_payment_type, migrations.RunPython.noop),
    ]
