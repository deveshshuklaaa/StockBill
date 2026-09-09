"""Import the Chheda product catalogue from the extracted PDF source data.

Transactional, idempotent, duplicate-safe importer for the 109-row Chheda
catalogue. Creates product master data ONLY:

- Product core: name (verbatim), MRP, Packaged Food category, piece base unit,
  manufacturer Supplier link
- Dynamic attributes: net_weight (kg decimal, verbatim source value) and
  units_per_master_box (integer, catalogue metadata)
- SKU: left blank (none in source; no fabrication)
- GST/HSN: left unset (none in source; never inferred)
- cost_price / default_price: left at the schema's zero default (never invented)

It never creates InventoryBalance, StockLedger entries, purchases, or payments.

Usage:
    python manage.py import_chheda_catalogue --dry-run
    python manage.py import_chheda_catalogue
"""

import json
from decimal import Decimal

from django.db import transaction
from django.core.management.base import BaseCommand, CommandError

from inventory.attribute_services import validate_and_normalize_attributes
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    Supplier,
)

SOURCE_FILE = "chheda_catalogue.json"

CATEGORY_CODE = "packaged-food"
CATEGORY_NAME = "Packaged Food"
NET_WEIGHT_CODE = "net_weight"
MASTER_BOX_CODE = "units_per_master_box"

MANUFACTURERS = [
    "Chheda Specialities Foods Pvt. Ltd.",
    "Chheda Agro Food Park Private Ltd.",
]


def load_rows():
    """Load and validate the 109-row source catalogue (shared with tests)."""
    import os

    path = os.path.join(os.path.dirname(__file__), SOURCE_FILE)
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    if len(rows) != 109:
        raise CommandError(f"Expected 109 source rows, found {len(rows)}.")
    serials = sorted(r["serial"] for r in rows)
    if serials != list(range(1, 110)):
        raise CommandError("Source serials must be exactly 1..109 without gaps.")
    return rows


class Command(BaseCommand):
    help = "Import the 109-row Chheda catalogue (dry-run capable, idempotent, transactional)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the reconciliation without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Chheda catalogue import" + (" (DRY RUN)" if dry_run else "")
            )
        )

        rows = self.load_source_rows()

        results = []
        with transaction.atomic():
            # Ensure category + attribute structure exists (idempotent).
            category, net_weight, master_box = self.ensure_structure()

            # Ensure manufacturer/supplier records exist (idempotent).
            suppliers = {
                name: Supplier.objects.filter(name=name).first()
                or Supplier.objects.create(name=name)
                for name in MANUFACTURERS
            }

            for row in rows:
                results.append(
                    self.process_row(row, category, net_weight, master_box, suppliers)
                )

            ambiguous = [r for r in results if r["status"] == "AMBIGUOUS"]
            if ambiguous and not dry_run:
                raise CommandError(
                    "Ambiguous variants detected; rolling back the entire import: "
                    + "; ".join(
                        f"row {r['serial']} ({r['name']}, {r['mrp']})"
                        for r in ambiguous
                    )
                )

            # Verify duplicate-safety: after processing, the exact-variant key
            # (name, category, supplier, mrp, attributes) must be unique.
            seen = {}
            for r in results:
                if r["status"] not in ("CREATED", "REUSED"):
                    continue
                key = (
                    r["name"].lower(),
                    r["supplier"],
                    r["mrp"],
                    r["net_weight"],
                    r["master_box"],
                )
                if key in seen:
                    raise CommandError(
                        f"Source rows {seen[key]} and {r['serial']} resolve to the same variant; "
                        "refusing to import ambiguous rows."
                    )
                seen[key] = r["serial"]

            if dry_run:
                transaction.set_rollback(True)

        self.report(rows, results, dry_run)

    # ------------------------------------------------------------------ helpers

    def load_source_rows(self):
        rows = load_rows()
        for row in rows:
            if row["manufacturer"] not in MANUFACTURERS:
                raise CommandError(
                    f"Row {row['serial']}: unknown manufacturer {row['manufacturer']!r}."
                )
        return rows

    def ensure_structure(self):
        notes = []
        category = Category.objects.filter(code=CATEGORY_CODE).first()
        if category is None:
            category = Category.objects.create(
                code=CATEGORY_CODE,
                name=CATEGORY_NAME,
                description="Packaged snacks and foods",
            )
            notes.append("category created")
        else:
            notes.append("category reused")

        net_weight = AttributeDefinition.objects.filter(code=NET_WEIGHT_CODE).first()
        if net_weight is None:
            net_weight = AttributeDefinition.objects.create(
                code=NET_WEIGHT_CODE,
                name="Net Weight",
                data_type=AttributeDefinition.TYPE_DECIMAL,
                unit="kg",
                decimal_places=3,
            )
            notes.append("net_weight attribute created")
        else:
            notes.append("net_weight attribute reused")

        master_box = AttributeDefinition.objects.filter(code=MASTER_BOX_CODE).first()
        if master_box is None:
            master_box = AttributeDefinition.objects.create(
                code=MASTER_BOX_CODE,
                name="Units per Master Box",
                data_type=AttributeDefinition.TYPE_INTEGER,
            )
            notes.append("units_per_master_box attribute created")
        else:
            notes.append("units_per_master_box attribute reused")

        for order, definition in enumerate((net_weight, master_box), start=1):
            assignment, created_assignment = CategoryAttribute.objects.get_or_create(
                category=category,
                attribute_definition=definition,
                defaults={"is_required": True, "display_order": order},
            )
            if created_assignment:
                notes.append(
                    f"{definition.code} assigned to {CATEGORY_NAME} (required)"
                )
        self.structure_notes = notes
        return category, net_weight, master_box

    def process_row(self, row, category, net_weight, master_box, suppliers):
        serial = row["serial"]
        name = row["name"].strip()
        mrp = Decimal(row["mrp"])
        net_weight_value = Decimal(row["net_weight_kg"])
        master_box_value = int(row["units_per_master_box"])

        if not name:
            return {"serial": serial, "status": "ERROR", "reason": "empty product name"}
        if net_weight_value <= 0 or master_box_value <= 0 or mrp < 0:
            return {
                "serial": serial,
                "status": "ERROR",
                "reason": "invalid numeric value",
            }

        # Exact-variant match: same name (case-insensitive) + category + MRP +
        # supplier + same attribute values. Any attribute difference keeps rows
        # separate; multiple exact matches abort the import as AMBIGUOUS.
        existing = self.find_existing_variant(
            name,
            category,
            mrp,
            net_weight,
            master_box,
            net_weight_value,
            master_box_value,
            suppliers[row["manufacturer"]],
        )
        if existing == "AMBIGUOUS":
            return {
                "serial": serial,
                "status": "AMBIGUOUS",
                "name": name,
                "mrp": mrp,
                "net_weight": net_weight_value,
                "master_box": master_box_value,
                "supplier": row["manufacturer"],
                "reason": "multiple exact variants already exist; cannot reconcile",
            }
        if existing is not None:
            return {
                "serial": serial,
                "status": "REUSED",
                "product_id": existing.pk,
                "name": existing.name,
                "mrp": existing.mrp,
                "net_weight": net_weight_value,
                "master_box": master_box_value,
                "supplier": row["manufacturer"],
                "reason": "exact variant already exists",
            }

        product = Product.objects.create(
            name=name,
            mrp=mrp,
            catalogue_category=category,
            base_unit=Product.UNIT_PIECE,
            supplier=suppliers[row["manufacturer"]],
            # Deliberately not set: sku, tax, hsn_sac, cost_price, default_price,
            # current_stock, low_stock_threshold — none are in the source.
        )
        # Bypass API-layer duplicate guard for exact catalogue reuse; the command
        # applies attribute values through the same typed service validation.
        validated = validate_and_normalize_attributes(
            category,
            {NET_WEIGHT_CODE: net_weight_value, MASTER_BOX_CODE: master_box_value},
        )
        for definition, typed_value in validated:
            ProductAttributeValue.objects.create(
                product=product,
                attribute_definition=definition,
                value_number=typed_value
                if definition.data_type == AttributeDefinition.TYPE_DECIMAL
                else None,
                value_integer=typed_value
                if definition.data_type == AttributeDefinition.TYPE_INTEGER
                else None,
            )
        return {
            "serial": serial,
            "status": "CREATED",
            "product_id": product.pk,
            "name": product.name,
            "mrp": product.mrp,
            "net_weight": net_weight_value,
            "master_box": master_box_value,
            "supplier": row["manufacturer"],
        }

    def find_existing_variant(
        self,
        name,
        category,
        mrp,
        net_weight,
        master_box,
        net_weight_value,
        master_box_value,
        supplier,
    ):
        """Return the exact existing variant, or 'AMBIGUOUS' when identity is unclear.

        Exact identity: same name (case-insensitive) + category + MRP + supplier +
        same net_weight and units_per_master_box. A candidate sharing name+MRP but
        differing in weight/box/supplier is a DIFFERENT variant, not a match.
        Multiple exact matches mean the data cannot be reconciled -> AMBIGUOUS.
        """
        candidates = Product.objects.filter(
            name__iexact=name,
            catalogue_category=category,
            mrp=mrp,
            supplier=supplier,
        )
        exact = []
        for candidate in candidates:
            weight = ProductAttributeValue.objects.filter(
                product=candidate, attribute_definition=net_weight
            ).first()
            box = ProductAttributeValue.objects.filter(
                product=candidate, attribute_definition=master_box
            ).first()
            if (
                weight is not None
                and weight.value_number == net_weight_value
                and box is not None
                and box.value_integer == master_box_value
            ):
                exact.append(candidate)
        if len(exact) > 1:
            return "AMBIGUOUS"
        return exact[0] if exact else None

    def report(self, rows, results, dry_run):
        created = [r for r in results if r["status"] == "CREATED"]
        reused = [r for r in results if r["status"] == "REUSED"]
        errors = [r for r in results if r["status"] == "ERROR"]
        ambiguous = [r for r in results if r["status"] == "AMBIGUOUS"]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("SUMMARY"))
        self.stdout.write(f"SOURCE ROWS: {len(rows)}")
        self.stdout.write(f"PARSED: {len(rows) - len(errors)}")
        self.stdout.write(f"NEW: {len(created)}")
        self.stdout.write(f"REUSED: {len(reused)}")
        self.stdout.write(f"AMBIGUOUS: {len(ambiguous)}")
        self.stdout.write(f"ERRORS: {len(errors)}")
        self.stdout.write(f"GST missing: {len(rows)} (not in source; left unset)")
        self.stdout.write(f"HSN/SAC missing: {len(rows)} (not in source; left blank)")
        self.stdout.write(
            f"COST PRICE missing: {len(rows)} (not in source; left at zero default)"
        )
        self.stdout.write(
            f"DEFAULT SELLING PRICE missing: {len(rows)} (not in source; left at zero default)"
        )
        self.stdout.write(f"SKU not supplied: {len(rows)} (left unset; no fabrication)")
        self.stdout.write("OPENING STOCK: 0 (M.Box is catalogue metadata only)")
        self.stdout.write(
            f"STRUCTURE: {', '.join(getattr(self, 'structure_notes', []))}"
        )
        supplier_counts = {}
        for r in results:
            supplier_counts[r["supplier"]] = supplier_counts.get(r["supplier"], 0) + 1
        for supplier, count in supplier_counts.items():
            self.stdout.write(f"SUPPLIER {supplier}: {count}")

        if ambiguous:
            self.stdout.write(
                self.style.ERROR("\nAMBIGUOUS (import would be rolled back):")
            )
            for r in ambiguous:
                self.stdout.write(
                    self.style.ERROR(f"  row {r['serial']}: {r['reason']}")
                )
        if errors:
            self.stdout.write(self.style.ERROR("\nERRORS:"))
            for r in errors:
                self.stdout.write(
                    self.style.ERROR(f"  row {r['serial']}: {r['reason']}")
                )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("RECONCILIATION"))
        for r in results:
            product_id = r.get("product_id")
            line = (
                f"{r['serial']:>3} | {r.get('supplier', '-')[:22]:<22} | "
                f"{r.get('name', '?'):<52} | {r.get('net_weight', '-')} | "
                f"{r.get('master_box', '-'):>3} | {r.get('mrp', '-'):>6} | "
                f"Product {product_id if product_id else '-'} | {r['status']}"
            )
            if r["status"] in ("REUSED", "AMBIGUOUS"):
                line += f" ({r['reason']})"
            self.stdout.write(line)
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no data was written."))
        else:
            self.stdout.write(self.style.SUCCESS("Import committed."))
