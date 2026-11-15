"""CSV helper and inventory stock export (GET /api/reports/inventory/export/)."""

import codecs
import csv
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient, APITestCase

from billing.csv_export import csv_response, excel_text, safe_text
from billing.reports import _inventory_valuation_rows, _legacy_inventory_products
from inventory.models import Category, Product, StockLedger, TaxRate, Warehouse
from inventory.services import adjust_inventory, ensure_inventory_balance

INVENTORY_HEADERS = ["SKU", "Product name", "Brand", "Category", "Warehouse", "Quantity on hand", "Base unit"]


def parse_csv(response):
    body = response.content
    assert body.startswith(codecs.BOM_UTF8), "CSV must start with a UTF-8 BOM"
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline="")))


class CsvHelperTests(SimpleTestCase):
    def test_formula_prefixes_escaped_only_in_text_columns(self):
        for raw in ['=HYPERLINK("x")', "+91 98200", "-cmd", "@SUM(A1)", "\t=1", "\r=1"]:
            self.assertTrue(safe_text(raw).startswith("'"), raw)
        response = csv_response(
            headers=["Name", "Amount"],
            rows=[["=1+1", "-1500.00"]],
            filename="x.csv",
            text_columns={"Name"},
        )
        rows = parse_csv(response)
        self.assertEqual(rows[1], ["'=1+1", "-1500.00"])

    def test_excel_text_keeps_codes_as_text_and_cannot_break_out(self):
        self.assertEqual(excel_text("9820098200"), '="9820098200"')
        self.assertEqual(excel_text("07"), '="07"')
        self.assertEqual(excel_text("+919820098200"), '="+919820098200"')
        self.assertEqual(excel_text('1"&HYPERLINK("x")&"'), '="1""&HYPERLINK(""x"")&"""')
        self.assertEqual(excel_text("\r\n411001"), '="411001"')
        self.assertEqual(excel_text(""), "")
        self.assertEqual(excel_text(None), "")
        self.assertEqual(excel_text("=" + "9" * 300), "'=" + "9" * 300)  # too long for an Excel literal
        response = csv_response(
            headers=["Phone", "Amount"], rows=[["9820098200", "-5.00"]], filename="x.csv",
            text_columns={"Phone"}, excel_text_columns={"Phone"},
        )
        self.assertEqual(parse_csv(response)[1], ['="9820098200"', "-5.00"])
        with self.assertRaises(ValueError):
            csv_response(headers=["A"], rows=[], filename="f.csv", text_columns=set(), excel_text_columns={"A"})

    def test_multiline_flattened_and_none_empty(self):
        self.assertEqual(safe_text("Shop 4,\r\nMarket Road\n\nPune "), "Shop 4,, Market Road, Pune")
        self.assertEqual(safe_text(None), "")

    def test_response_headers_and_unknown_text_column(self):
        response = csv_response(headers=["A"], rows=[["₹ नमस्ते"]], filename="f.csv", text_columns={"A"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="f.csv"')
        self.assertEqual(parse_csv(response)[1], ["₹ नमस्ते"])
        with self.assertRaises(ValueError):
            csv_response(headers=["A"], rows=[], filename="f.csv", text_columns={"B"})


class InventoryStockExportTests(APITestCase):
    URL = "/api/reports/inventory/export/"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(username="inv-admin", password="P123!", role="admin")
        cls.staff = User.objects.create_user(username="inv-staff", password="P123!", role="staff")
        tax = TaxRate.objects.create(name="GST 5 export", rate=Decimal("5.00"))
        cls.category = Category.objects.create(code="SNK", name="Snacks")
        cls.godown = Warehouse.objects.create(name="Godown 2", code="GD2")

        def product(name, sku, stock, **extra):
            return Product.objects.create(
                name=name, sku=sku, brand="Chheda", tax=tax, cost_price=Decimal("7.50"),
                default_price=10, current_stock=stock, unit_type="piece", unit_conversion_factor=1, **extra
            )

        cls.chips = product("Banana Chips", "CH-1", Decimal("120"), catalogue_category=cls.category)
        cls.mix = product("=Mixture", "CH-2", Decimal("40"))
        cls.archived = product("Old Namkeen", "CH-3", Decimal("5"), is_active=False)
        cls.empty = product("Sold Out", "CH-4", Decimal("0"))
        for p in (cls.chips, cls.mix, cls.archived, cls.empty):
            ensure_inventory_balance(product=p)
        adjust_inventory(product=cls.chips, quantity_delta=Decimal("12.5"), movement_type=StockLedger.ADJUSTMENT, unit_cost=Decimal("7.50"), warehouse=cls.godown)

    def client_as(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def expected_rows(self, **filters):
        balances = _inventory_valuation_rows(**filters).order_by("product__name", "warehouse__code", "id")
        rows = [
            [b.product.sku, b.product.name, b.product.brand,
             b.product.catalogue_category.name if b.product.catalogue_category else "",
             b.warehouse.name, f"{b.quantity_on_hand:.3f}", b.product.base_unit]
            for b in balances
        ]
        legacy = _legacy_inventory_products(**filters)
        rows += [[p.sku, p.name, p.brand, "", "", f"{p.current_stock:.3f}", p.base_unit] for p in legacy]
        # Text cells go through the same escaping as the export; quantity (index 5) does not.
        return [[cell if i == 5 else safe_text(cell) for i, cell in enumerate(row)] for row in rows]

    def test_staff_gets_csv_matching_row_builder(self):
        response = self.client_as(self.staff).get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertRegex(response["Content-Disposition"], r'attachment; filename="stockbill-inventory-\d{8}-\d{4}\.csv"')
        rows = parse_csv(response)
        self.assertEqual(rows[0], INVENTORY_HEADERS)
        self.assertEqual(rows[1:], self.expected_rows(warehouse=None, category=None, is_active=None, search=""))
        names = [r[1] for r in rows[1:]]
        self.assertIn("Banana Chips", names)
        self.assertNotIn("Sold Out", names)  # zero stock is not "stock left"

    def test_quantity_total_matches_inventory_report_screen(self):
        csv_rows = parse_csv(self.client_as(self.staff).get(self.URL))[1:]
        screen = self.client_as(self.staff).get("/api/reports/inventory/").data
        self.assertEqual(sum(Decimal(r[5]) for r in csv_rows), Decimal(screen["quantity_on_hand"]))

    def test_per_warehouse_rows_and_no_cost_columns(self):
        rows = parse_csv(self.client_as(self.staff).get(self.URL, {"search": "banana"}))
        self.assertEqual(rows[1:], [
            ["CH-1", "Banana Chips", "Chheda", "Snacks", "Godown 2", "12.500", "piece"],
            ["CH-1", "Banana Chips", "Chheda", "Snacks", "Main Warehouse", "120.000", "piece"],
        ])
        self.assertFalse({"Average cost", "Stock value", "Value"} & set(rows[0]))

    def test_filters_match_screen(self):
        for params, filters in [
            ({"warehouse": str(self.godown.pk)}, {"warehouse": self.godown, "category": None, "is_active": None, "search": ""}),
            ({"is_active": "false"}, {"warehouse": None, "category": None, "is_active": False, "search": ""}),
            ({"category": str(self.category.pk)}, {"warehouse": None, "category": self.category, "is_active": None, "search": ""}),
        ]:
            rows = parse_csv(self.client_as(self.staff).get(self.URL, params))[1:]
            self.assertEqual([r[0] for r in rows], [r[0] for r in self.expected_rows(**filters)], params)
        self.assertEqual([r[1] for r in parse_csv(self.client_as(self.staff).get(self.URL, {"is_active": "false"}))[1:]], ["Old Namkeen"])

    def test_formula_like_product_name_is_escaped(self):
        rows = parse_csv(self.client_as(self.staff).get(self.URL, {"search": "CH-2"}))
        self.assertEqual(rows[1][1], "'=Mixture")
        self.assertEqual(rows[1][5], "40.000")

    def test_bad_filter_and_permissions(self):
        self.assertEqual(self.client_as(self.staff).get(self.URL, {"warehouse": "abc"}).status_code, 400)
        self.assertEqual(self.client_as(self.admin).get(self.URL).status_code, 200)
        self.assertIn(self.client_as(None).get(self.URL).status_code, {401, 403})
