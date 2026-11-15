import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema for server-assigned GST invoice numbers.

    invoice_number becomes nullable (drafts carry no number) but keeps
    max_length=50 so legacy INV-YYYYMMDDHHMMSS numbers stay valid as-is.
    invoice_date stops being auto_now_add; posting sets the IST issue date.
    No existing row is modified here.
    """

    dependencies = [
        ("billing", "0014_add_amendment_links"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceNumberCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fy_code", models.CharField(max_length=10, unique=True)),
                ("last_serial", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="CreditNoteNumberCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fy_code", models.CharField(max_length=10, unique=True)),
                ("last_serial", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AlterField(
            model_name="invoice",
            name="invoice_number",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="invoice_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
