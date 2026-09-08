from decimal import Decimal

from django.db import migrations, models
import django.conf
import django.core.validators
import django.db.models.deletion


def seed_main_warehouse(apps, schema_editor):
    Product = apps.get_model("inventory", "Product")
    Warehouse = apps.get_model("inventory", "Warehouse")
    InventoryBalance = apps.get_model("inventory", "InventoryBalance")
    StockLedger = apps.get_model("inventory", "StockLedger")

    warehouse, _ = Warehouse.objects.get_or_create(
        code="MAIN",
        defaults={"name": "Main Warehouse", "address": ""},
    )
    for product in Product.objects.all().iterator():
        quantity = product.current_stock or Decimal("0.000")
        InventoryBalance.objects.get_or_create(
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            defaults={"quantity_on_hand": quantity},
        )
        if quantity:
            StockLedger.objects.create(
                product_id=product.pk,
                warehouse_id=warehouse.pk,
                quantity_change=quantity,
                quantity_delta=quantity,
                movement_type="OPENING_STOCK",
                reference_type="migration",
                reference_id=product.pk,
                reason="One-time migration from Product.current_stock",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="base_unit",
            field=models.CharField(choices=[("carton", "Carton"), ("box", "Box"), ("piece", "Piece")], default="piece", max_length=20),
        ),
        migrations.AddField(
            model_name="product",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="stock_movements", to=django.conf.settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="quantity_delta",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="reference_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="reference_type",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="stockledger",
            name="unit_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="product",
            name="unit_conversion_factor",
            field=models.DecimalField(decimal_places=3, default=1, max_digits=12, validators=[django.core.validators.MinValueValidator(0.001)]),
        ),
        migrations.AlterField(
            model_name="stockledger",
            name="movement_type",
            field=models.CharField(choices=[("OPENING_STOCK", "Opening Stock"), ("PURCHASE", "Purchase"), ("SALE", "Sale"), ("SALES_RETURN", "Sales Return"), ("PURCHASE_RETURN", "Purchase Return"), ("DAMAGE", "Damage"), ("ADJUSTMENT", "Adjustment"), ("TRANSFER_IN", "Transfer In"), ("TRANSFER_OUT", "Transfer Out")], default="ADJUSTMENT", max_length=20),
        ),
        migrations.CreateModel(
            name="InventoryBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity_on_hand", models.DecimalField(decimal_places=3, max_digits=12, validators=[django.core.validators.MinValueValidator(0)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inventory_balances", to="inventory.product")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inventory_balances", to="inventory.warehouse")),
            ],
        ),
        migrations.AddConstraint(
            model_name="inventorybalance",
            constraint=models.UniqueConstraint(fields=("product", "warehouse"), name="unique_product_warehouse_balance"),
        ),
        migrations.AddIndex(
            model_name="stockledger",
            index=models.Index(fields=["product", "warehouse", "created_at"], name="inventory_s_product__f3c0dc_idx"),
        ),
        migrations.RunPython(seed_main_warehouse, migrations.RunPython.noop),
    ]
