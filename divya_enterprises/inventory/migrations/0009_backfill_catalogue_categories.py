from django.db import migrations
from django.utils.text import slugify


def backfill_catalogue_categories(apps, schema_editor):
    """Create Category rows from distinct legacy Product.category text values.

    Blank/None legacy categories are left with catalogue_category NULL — no category
    is invented. Product IDs, inventory, invoices, COGS, and GST data are untouched.
    """
    Product = apps.get_model("inventory", "Product")
    Category = apps.get_model("inventory", "Category")

    mapping = {}
    for legacy_name in (
        Product.objects.exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    ):
        legacy_name = legacy_name.strip()
        if not legacy_name:
            continue
        category, _ = Category.objects.get_or_create(
            name=legacy_name,
            defaults={
                "code": slugify(legacy_name)[:50] or f"category-{len(mapping) + 1}"
            },
        )
        mapping[legacy_name] = category
    for legacy_name, category in mapping.items():
        Product.objects.filter(category=legacy_name).update(catalogue_category=category)


def unbackfill_catalogue_categories(apps, schema_editor):
    Product = apps.get_model("inventory", "Product")
    Product.objects.update(catalogue_category=None)


class Migration(migrations.Migration):
    dependencies = [
        (
            "inventory",
            "0008_attributedefinition_category_product_mrp_product_sku_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_catalogue_categories, unbackfill_catalogue_categories
        ),
    ]
