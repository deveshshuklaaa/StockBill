from django.db import migrations


def backfill_average_cost(apps, schema_editor):
    InventoryBalance = apps.get_model("inventory", "InventoryBalance")
    for balance in InventoryBalance.objects.select_related("product").all().iterator():
        if balance.average_cost == 0 and balance.product.cost_price:
            balance.average_cost = balance.product.cost_price
            balance.save(update_fields=["average_cost"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_inventorybalance_average_cost_purchaseinvoice_and_more"),
    ]

    operations = [migrations.RunPython(backfill_average_cost, migrations.RunPython.noop)]
