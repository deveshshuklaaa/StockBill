from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditnotelineitem",
            name="invoice_line_item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="credit_note_reversals",
                to="billing.invoicelineitem",
            ),
        ),
        migrations.AlterField(
            model_name="payment",
            name="customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payments",
                to="customers.customer",
            ),
        ),
    ]
