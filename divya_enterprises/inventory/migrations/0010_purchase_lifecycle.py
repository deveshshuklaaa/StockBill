import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def backfill_purchase_history(apps, schema_editor):
    """Map existing purchase rows onto the new lifecycle schema.

    Existing purchases already moved stock through the legacy receive flow,
    so they are POSTED: their supplier bill number keeps its old value, the
    internal purchase number is assigned in FY-of-invoice_date serial order,
    tax columns stay zero (they were never recorded), and line snapshots are
    reconstructed from the current masters.
    """
    from inventory.purchase_numbering import financial_year_code

    PurchaseInvoice = apps.get_model("inventory", "PurchaseInvoice")
    PurchaseLineItem = apps.get_model("inventory", "PurchaseLineItem")

    ordered = list(PurchaseInvoice.objects.order_by("invoice_date", "id"))
    counters = {}
    for purchase in ordered:
        purchase.state = "POSTED"
        purchase.posted_at = purchase.created_at or timezone.now()
        purchase.supplier_invoice_no = purchase.invoice_number or ""
        fy = financial_year_code(purchase.invoice_date)
        counters[fy] = counters.get(fy, 0) + 1
        purchase.purchase_number = f"PI/{fy}/{counters[fy]:06d}"
        supplier = purchase.supplier
        purchase.supplier_name_snapshot = supplier.name
        purchase.supplier_gstin_snapshot = supplier.gstin
        purchase.supplier_state_snapshot = supplier.state
        purchase.supplier_state_code_snapshot = supplier.state_code
        purchase.save(
            update_fields=[
                "state",
                "posted_at",
                "supplier_invoice_no",
                "purchase_number",
                "supplier_name_snapshot",
                "supplier_gstin_snapshot",
                "supplier_state_snapshot",
                "supplier_state_code_snapshot",
            ]
        )
        for line in PurchaseLineItem.objects.filter(purchase_invoice=purchase):
            line.product_name_snapshot = line.product.name
            line.sku_snapshot = line.product.sku or ""
            line.hsn_sac_snapshot = line.product.hsn_sac
            line.base_unit_snapshot = line.product.base_unit
            line.purchase_unit_name = line.product.base_unit
            line.conversion_factor = 1
            line.base_quantity = line.quantity
            line.rate = line.unit_cost
            line.taxable_value = line.line_total
            line.unit_cost_snapshot = line.unit_cost
            line.save(
                update_fields=[
                    "product_name_snapshot",
                    "sku_snapshot",
                    "hsn_sac_snapshot",
                    "base_unit_snapshot",
                    "purchase_unit_name",
                    "conversion_factor",
                    "base_quantity",
                    "rate",
                    "taxable_value",
                    "unit_cost_snapshot",
                ]
            )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0009_backfill_catalogue_categories"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier",
            name="gstin",
            field=models.CharField(blank=True, max_length=15),
        ),
        migrations.AddField(
            model_name="supplier",
            name="address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="supplier",
            name="state",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="supplier",
            name="state_code",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="supplier",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="purchase_number",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="supplier_invoice_no",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="state",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("POSTED", "Posted"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="DRAFT",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="tax_mode",
            field=models.CharField(
                choices=[("exclusive", "Exclusive"), ("inclusive", "Inclusive")],
                default="exclusive",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="supplier_name_snapshot",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="supplier_gstin_snapshot",
            field=models.CharField(blank=True, max_length=25),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="supplier_state_snapshot",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="supplier_state_code_snapshot",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="subtotal",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="discount_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="taxable_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="cgst_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="sgst_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="igst_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="cancellation_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="cancelled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cancelled_purchase_invoices",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="posted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="product_name_snapshot",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="sku_snapshot",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="hsn_sac_snapshot",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="base_unit_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="purchase_unit_name",
            field=models.CharField(default="piece", max_length=50),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="conversion_factor",
            field=models.DecimalField(
                decimal_places=3,
                default=1,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(0.001)],
            ),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="base_quantity",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="rate",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="discount_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="cgst_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="cgst_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="sgst_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="sgst_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="igst_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="igst_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="taxable_value",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="unit_cost_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaselineitem",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.RemoveField(
            model_name="purchaselineitem",
            name="unit_cost",
        ),
        migrations.RemoveField(
            model_name="purchaseinvoice",
            name="invoice_number",
        ),
        migrations.AlterUniqueTogether(
            name="purchaseinvoice",
            unique_together=set(),
        ),
        migrations.RunPython(backfill_purchase_history, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="purchaseinvoice",
            constraint=models.UniqueConstraint(
                fields=["supplier", "supplier_invoice_no"],
                name="unique_supplier_invoice_no_per_supplier",
                condition=~models.Q(supplier_invoice_no=""),
            ),
        ),
        migrations.CreateModel(
            name="PurchaseNumberCounter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("fy_code", models.CharField(max_length=10, unique=True)),
                ("last_serial", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="PurchaseIdempotencyKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=255, unique=True)),
                ("request_hash", models.CharField(default="", max_length=64)),
                (
                    "purchase",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="idempotency_record",
                        to="inventory.purchaseinvoice",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AlterField(
            model_name="stockledger",
            name="movement_type",
            field=models.CharField(
                choices=[
                    ("OPENING_STOCK", "Opening Stock"),
                    ("PURCHASE", "Purchase"),
                    ("PURCHASE_REVERSAL", "Purchase Reversal"),
                    ("SALE", "Sale"),
                    ("SALE_REVERSAL", "Sale Reversal"),
                    ("SALES_RETURN", "Sales Return"),
                    ("PURCHASE_RETURN", "Purchase Return"),
                    ("DAMAGE", "Damage"),
                    ("ADJUSTMENT", "Adjustment"),
                    ("TRANSFER_IN", "Transfer In"),
                    ("TRANSFER_OUT", "Transfer Out"),
                ],
                default="ADJUSTMENT",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseinvoice",
            index=models.Index(
                fields=["supplier", "supplier_invoice_no"],
                name="inventory_p_supplie_1065a6_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseinvoice",
            index=models.Index(
                fields=["state", "-invoice_date"],
                name="inventory_p_state_32d7e3_idx",
            ),
        ),
    ]
