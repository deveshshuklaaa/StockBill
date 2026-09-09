"""Tests for the Chheda catalogue importer: parsing, idempotency, variant
separation, value preservation, and no-inventory/no-financial-invention guarantees."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from io import StringIO

from .management.commands import import_chheda_catalogue
from .management.commands.import_chheda_catalogue import load_rows
from .models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    StockLedger,
    Supplier,
)

User = get_user_model()

SPECIALITIES = "Chheda Specialities Foods Pvt. Ltd."
AGRO_PARK = "Chheda Agro Food Park Private Ltd."


def run_import(dry_run=False):
    out = StringIO()
    call_command("import_chheda_catalogue", dry_run=dry_run, stdout=out)
    return out.getvalue()


class ChhedaImportTests(TestCase):
    def setUp(self):
        self.pre_products = list(Product.objects.values_list("id", flat=True))

    # 1. all rows parse and import
    def test_all_109_rows_import(self):
        output = run_import()
        self.assertIn("SOURCE ROWS: 109", output)
        self.assertIn("NEW: 109", output)
        self.assertIn("REUSED: 0", output)
        self.assertIn("ERRORS: 0", output)
        self.assertEqual(Product.objects.count(), len(self.pre_products) + 109)

    # 2. rerun creates no duplicates
    def test_rerun_is_idempotent(self):
        run_import()
        first_ids = set(Product.objects.values_list("id", flat=True))
        output = run_import()
        self.assertIn("NEW: 0", output)
        self.assertIn("REUSED: 109", output)
        self.assertEqual(Product.objects.count(), len(first_ids))

    # 3. same name / different weight stay separate
    def test_same_name_different_weight_separate(self):
        run_import()
        # Serial 1 vs 15: Yellow banana Chips at 0.014 vs 0.025
        light = Product.objects.filter(
            name__iexact="Chheda's Yellow banana Chips", mrp=Decimal("5.00")
        ).get()
        mid = Product.objects.filter(
            name__iexact="Chheda's Yellow banana Chips", mrp=Decimal("10.00")
        ).get()
        heavy = Product.objects.filter(
            name__iexact="Chheda's Yellow banana Chips", mrp=Decimal("20.00")
        ).get()
        self.assertNotEqual(light.id, mid.id)
        self.assertNotEqual(mid.id, heavy.id)
        weights = {
            self.attribute(light, "net_weight"),
            self.attribute(mid, "net_weight"),
            self.attribute(heavy, "net_weight"),
        }
        self.assertEqual(
            weights, {Decimal("0.014"), Decimal("0.025"), Decimal("0.030")}
        )

    # 4. same name / different MRP stay separate
    def test_same_name_different_mrp_separate(self):
        run_import()
        # Farali Potato Chivda appears at MRP 5/10/20 with distinct weights
        chivda = Product.objects.filter(name__iexact="Chheda's Farali Potato Chivda")
        self.assertEqual(chivda.count(), 3)
        self.assertEqual(
            set(chivda.values_list("mrp", flat=True)),
            {Decimal("5.00"), Decimal("10.00"), Decimal("20.00")},
        )

    # 5. MRP preserved
    def test_mrp_preserved(self):
        run_import()
        product = Product.objects.get(
            name="Chheda's Yellow banana Chips", mrp=Decimal("5.00")
        )
        self.assertEqual(product.mrp, Decimal("5.00"))
        finger_pops = Product.objects.get(
            name="Chheda's Finger Pops Masala", mrp=Decimal("20.00")
        )
        self.assertEqual(finger_pops.mrp, Decimal("20.00"))

    # 6. Gms preserved as kg decimal (verbatim magnitude)
    def test_net_weight_stored_as_kg_decimal(self):
        run_import()
        # Row 15 is "Yellow Banana Chips" (capital B in source); 0.025 kg stays 0.025
        product = Product.objects.get(
            name="Chheda's Yellow Banana Chips", mrp=Decimal("10.00")
        )
        self.assertEqual(self.attribute(product, "net_weight"), Decimal("0.025"))
        # 52 g -> 0.052 (French Fries), never 52
        fries = Product.objects.get(
            name="Chheda's Salted French Fries", mrp=Decimal("20.00")
        )
        self.assertEqual(self.attribute(fries, "net_weight"), Decimal("0.052"))

    # 7. M.Box preserved as integer metadata
    def test_master_box_integer_preserved(self):
        run_import()
        product = Product.objects.get(
            name="Chheda's Yellow banana Chips", mrp=Decimal("5.00")
        )
        self.assertEqual(self.attribute(product, "units_per_master_box"), 240)
        chana = Product.objects.get(name="Chheda's Chana Dal", mrp=Decimal("5.00"))
        self.assertEqual(self.attribute(chana, "units_per_master_box"), 600)

    # 8+9. no inventory or ledger rows created
    def test_no_inventory_or_stock_ledger_created(self):
        run_import()
        self.assertEqual(InventoryBalance.objects.count(), 0)
        self.assertEqual(StockLedger.objects.count(), 0)
        imported = Product.objects.exclude(id__in=self.pre_products)
        for product in imported[:20]:
            self.assertEqual(product.current_stock, Decimal("0"))

    # 10. no fake GST/HSN
    def test_no_gst_or_hsn_fabricated(self):
        run_import()
        imported = Product.objects.exclude(id__in=self.pre_products)
        self.assertEqual(imported.count(), 109)
        self.assertEqual(imported.filter(tax__isnull=False).count(), 0)
        self.assertEqual(imported.filter(hsn_sac__gt="").count(), 0)

    # 11. no fake cost price
    def test_no_cost_price_fabricated(self):
        run_import()
        imported = Product.objects.exclude(id__in=self.pre_products)
        self.assertEqual(imported.count(), 109)
        for product in imported:
            self.assertIn(product.cost_price, (None, Decimal("0"), Decimal("0.00")))

    # 12. manufacturer distinction preserved
    def test_manufacturer_distinction_preserved(self):
        run_import()
        specialities = Supplier.objects.get(name=SPECIALITIES)
        agro = Supplier.objects.get(name=AGRO_PARK)
        self.assertEqual(Product.objects.filter(supplier=specialities).count(), 41)
        self.assertEqual(Product.objects.filter(supplier=agro).count(), 68)
        # boundary rows: serial 41 -> Specialities, 42 -> Agro Park
        poha = Product.objects.get(
            name="Chheda's Light N Crispy Poha Chivda", mrp=Decimal("10.00")
        )
        self.assertEqual(poha.supplier, specialities)
        sabudana = Product.objects.get(
            name="Udupi Munch Sabudana Chivda", mrp=Decimal("5.00")
        )
        self.assertEqual(sabudana.supplier, agro)

    # 13. reconciliation covers every source row
    def test_reconciliation_accounts_for_every_row(self):
        output = run_import()
        self.assertIn("RECONCILIATION", output)
        # every serial 1..109 appears exactly once with a status
        import re

        lines = [
            line for line in output.splitlines() if re.match(r"^\s*\d+\s+\|", line)
        ]
        serials = [int(line.split("|")[0].strip()) for line in lines]
        self.assertEqual(sorted(serials), list(range(1, 110)))
        statuses = {line.rsplit("|", 1)[1].strip().split(" ")[0] for line in lines}
        self.assertEqual(statuses, {"CREATED"})

    # dry-run writes nothing
    def test_dry_run_writes_nothing(self):
        output = run_import(dry_run=True)
        self.assertIn("DRY RUN", output)
        self.assertIn("NEW: 109", output)
        self.assertEqual(Product.objects.count(), len(self.pre_products))
        self.assertFalse(Category.objects.filter(code="packaged-food").exists())
        self.assertFalse(Supplier.objects.filter(name=SPECIALITIES).exists())

    # names preserved verbatim: ASCII apostrophe for most rows, U+2019 where the
    # source uses it (serials 4/18/33 "Chilli Flaminn’") — no normalization.
    def test_names_preserved_verbatim(self):
        run_import()
        name = "Chheda's Yellow banana Chips"  # ASCII apostrophe, as in source
        self.assertTrue(Product.objects.filter(name=name).exists())
        flaminn = Product.objects.filter(name__contains="Flaminn", mrp=Decimal("5.00"))
        self.assertEqual(flaminn.count(), 1)
        self.assertIn("\u2019", flaminn.first().name)  # curly apostrophe preserved
        # lowercase "banana" in the source stays lowercase
        self.assertTrue(Product.objects.filter(name__iexact=name).count() >= 3)

    # attribute structure is created and reusable
    def test_structure_created_and_reused(self):
        run_import()
        category = Category.objects.get(code="packaged-food")
        self.assertEqual(
            AttributeDefinition.objects.filter(code="net_weight").count(), 1
        )
        self.assertEqual(
            CategoryAttribute.objects.filter(
                category=category, is_required=True
            ).count(),
            2,
        )
        output = run_import()
        self.assertIn("category reused", output)
        self.assertIn("net_weight attribute reused", output)

    # existing exact variants are reused, not duplicated
    def test_existing_exact_variant_reused(self):
        run_import()
        # simulate prior import existing: rerun and expect reuse only
        count_before = Product.objects.count()
        output = run_import()
        self.assertIn("NEW: 0", output)
        self.assertIn("REUSED: 109", output)
        self.assertEqual(Product.objects.count(), count_before)

    # base unit is the sellable packet
    def test_base_unit_is_piece(self):
        run_import()
        imported = Product.objects.exclude(id__in=self.pre_products)
        self.assertEqual(imported.count(), 109)
        self.assertEqual(imported.exclude(base_unit="piece").count(), 0)

    def attribute(self, product, code):
        return ProductAttributeValue.objects.get(
            product=product, attribute_definition__code=code
        ).typed_value()


class ChhedaSourceDataTests(TestCase):
    """Source-integrity checks: exactly 109 rows, complete serials, correct mapping."""

    def test_source_contains_exactly_109_rows(self):
        from .management.commands.import_chheda_catalogue import load_rows

        rows = load_rows()
        self.assertEqual(len(rows), 109)

    def test_source_serials_complete_1_to_109(self):
        from .management.commands.import_chheda_catalogue import load_rows

        serials = sorted(r["serial"] for r in load_rows())
        self.assertEqual(serials, list(range(1, 110)))

    def test_source_manufacturer_split_is_41_68(self):
        from .management.commands.import_chheda_catalogue import load_rows

        rows = load_rows()
        specialities = [r for r in rows if r["serial"] <= 41]
        agro = [r for r in rows if r["serial"] >= 42]
        self.assertEqual(len(specialities), 41)
        self.assertEqual(len(agro), 68)
        for r in specialities:
            self.assertEqual(r["manufacturer"], SPECIALITIES)
        for r in agro:
            self.assertEqual(r["manufacturer"], AGRO_PARK)

    def test_every_row_has_valid_values(self):
        from .management.commands.import_chheda_catalogue import load_rows
        from decimal import Decimal

        for r in load_rows():
            self.assertTrue(r["name"].strip(), f"row {r['serial']}: empty name")
            weight = Decimal(r["net_weight_kg"])
            self.assertGreater(weight, 0, f"row {r['serial']}: bad weight")
            self.assertIsInstance(r["units_per_master_box"], int)
            self.assertGreater(r["units_per_master_box"], 0)
            self.assertGreaterEqual(Decimal(r["mrp"]), 0)

    def test_supplier_counts_from_source(self):
        # boundary integrity: serial 41 Specialities, 42 Agro Park
        from .management.commands.import_chheda_catalogue import load_rows

        rows = {r["serial"]: r for r in load_rows()}
        self.assertEqual(rows[41]["manufacturer"], SPECIALITIES)
        self.assertEqual(rows[42]["manufacturer"], AGRO_PARK)


class ChhedaExampleRowTests(TestCase):
    """Mandatory example verification: rows 1, 15, 31, 109."""

    def setUp(self):
        run_import()

    def attr(self, product, code):
        return ProductAttributeValue.objects.get(
            product=product, attribute_definition__code=code
        ).typed_value()

    def test_row_1(self):
        product = Product.objects.get(
            name="Chheda's Yellow banana Chips", mrp=Decimal("5.00")
        )
        self.assertEqual(self.attr(product, "net_weight"), Decimal("0.014"))
        self.assertEqual(self.attr(product, "units_per_master_box"), 240)
        self.assertEqual(product.supplier.name, SPECIALITIES)

    def test_row_15(self):
        product = Product.objects.get(
            name="Chheda's Yellow Banana Chips", mrp=Decimal("10.00")
        )
        self.assertEqual(self.attr(product, "net_weight"), Decimal("0.025"))
        self.assertEqual(self.attr(product, "units_per_master_box"), 192)
        self.assertEqual(product.supplier.name, SPECIALITIES)

    def test_row_31_separate_from_row_15(self):
        row15 = Product.objects.get(
            name="Chheda's Yellow Banana Chips", mrp=Decimal("10.00")
        )
        row31 = Product.objects.get(
            name="Chheda's Yellow Banana Chips", mrp=Decimal("20.00")
        )
        self.assertNotEqual(row15.pk, row31.pk)
        self.assertEqual(self.attr(row31, "net_weight"), Decimal("0.030"))
        self.assertEqual(self.attr(row31, "units_per_master_box"), 120)

    def test_row_109(self):
        product = Product.objects.get(
            name="Potato Corn Stix Cream-n-Onion 52g", mrp=Decimal("20.00")
        )
        self.assertEqual(self.attr(product, "net_weight"), Decimal("0.052"))
        self.assertEqual(self.attr(product, "units_per_master_box"), 100)
        self.assertEqual(product.supplier.name, AGRO_PARK)

    def test_no_default_selling_price_invented(self):
        imported = Product.objects.filter(supplier__name__in=[SPECIALITIES, AGRO_PARK])
        self.assertEqual(imported.count(), 109)
        for product in imported:
            self.assertIn(product.default_price, (None, Decimal("0"), Decimal("0.00")))


class ChhedaAmbiguityAndRollbackTests(TestCase):
    """AMBIGUOUS variants must abort the actual import and roll back everything."""

    def make_ambiguous(self):
        """Duplicate row 15's exact variant manually to create ambiguity."""
        from .management.commands.import_chheda_catalogue import load_rows

        rows = load_rows()
        row15 = next(r for r in rows if r["serial"] == 15)
        category = Category.objects.create(code="packaged-food", name="Packaged Food")
        net_weight = AttributeDefinition.objects.create(
            code="net_weight",
            name="Net Weight",
            data_type=AttributeDefinition.TYPE_DECIMAL,
            unit="kg",
            decimal_places=3,
        )
        master_box = AttributeDefinition.objects.create(
            code="units_per_master_box",
            name="Units per Master Box",
            data_type=AttributeDefinition.TYPE_INTEGER,
        )
        for d in (net_weight, master_box):
            CategoryAttribute.objects.create(category=category, attribute_definition=d)
        supplier = Supplier.objects.create(name=SPECIALITIES)
        first = Product.objects.create(
            name=row15["name"],
            mrp=Decimal(row15["mrp"]),
            catalogue_category=category,
            base_unit="piece",
            supplier=supplier,
        )
        ProductAttributeValue.objects.create(
            product=first,
            attribute_definition=net_weight,
            value_number=Decimal(row15["net_weight_kg"]),
        )
        ProductAttributeValue.objects.create(
            product=first,
            attribute_definition=master_box,
            value_integer=row15["units_per_master_box"],
        )
        second = Product.objects.create(
            name=row15["name"],
            mrp=Decimal(row15["mrp"]),
            catalogue_category=category,
            base_unit="piece",
            supplier=supplier,
        )
        ProductAttributeValue.objects.create(
            product=second,
            attribute_definition=net_weight,
            value_number=Decimal(row15["net_weight_kg"]),
        )
        ProductAttributeValue.objects.create(
            product=second,
            attribute_definition=master_box,
            value_integer=row15["units_per_master_box"],
        )
        return first, second

    def test_ambiguous_duplicate_rejected_safely(self):
        first, second = self.make_ambiguous()
        with self.assertRaises(CommandError):
            run_import()
        # ambiguous existing rows remain untouched; nothing else imported
        self.assertTrue(Product.objects.filter(pk=first.pk).exists())
        self.assertTrue(Product.objects.filter(pk=second.pk).exists())
        # no catalogue products were created
        self.assertEqual(
            Product.objects.filter(
                supplier__name__in=[SPECIALITIES, AGRO_PARK]
            ).count(),
            2,
        )

    def test_failed_import_rolls_back_completely(self):
        from unittest.mock import patch

        with patch.object(
            import_chheda_catalogue.Command, "process_row", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                run_import()
        self.assertEqual(Product.objects.count(), 0)
        self.assertFalse(Category.objects.filter(code="packaged-food").exists())
        self.assertFalse(Supplier.objects.filter(name=SPECIALITIES).exists())
        self.assertEqual(ProductAttributeValue.objects.count(), 0)
