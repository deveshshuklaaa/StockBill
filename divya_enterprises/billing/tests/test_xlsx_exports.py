"""Excel helper and inventory stock export (GET /api/reports/inventory/export/)."""

import io
from decimal import Decimal

import openpyxl
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient, APITestCase

from billing.reports import _inventory_valuation_rows, _legacy_inventory_products
from billing.xlsx_export import HEADER_ROW, MONEY, QUANTITY, XLSX_CONTENT_TYPE, Column, flatten_text, xlsx_response
from inventory.models import Category, Product, StockLedger, TaxRate, Warehouse
from inventory.services import adjust_inventory, ensure_inventory_balance

INVENTORY_HEADERS = ["Product name", "MRP", "Quantity on hand", "Base unit"]


def read_sheet(response):
    """Return (sheet, header_values, data_rows) where data rows hold raw cell values."""
    assert response["Content-Type"] == XLSX_CONTENT_TYPE
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    sheet = workbook.active
    rows = list(sheet.iter_rows(min_row=HEADER_ROW, values_only=True))
    return sheet, list(rows[0]), [list(row) for row in rows[1:]]


class XlsxHelperTests(SimpleTestCase):
    def build(self, rows, columns=None):
        columns = columns or [Column("Name"), Column("Phone"), Column("Amount", MONEY), Column("Qty", QUANTITY)]
        return xlsx_response(title="Test", columns=columns, rows=rows, filename="t.xlsx")

    def test_formula_looking_text_is_stored_as_plain_text(self):
        sheet, _, rows = read_sheet(self.build([['=HYPERLINK("http://x")', "+919820098200", "-1500", "2.5"]]))
        name, phone = sheet.cell(row=HEADER_ROW + 1, column=1), sheet.cell(row=HEADER_ROW + 1, column=2)
        self.assertEqual(name.value, '=HYPERLINK("http://x")')
        self.assertEqual(name.data_type, "s")  # not "f": Excel will not evaluate it
        self.assertEqual(phone.data_type, "s")
        self.assertEqual(rows[0][2], -1500)  # numeric money stays a real (negative) number
        self.assertEqual(rows[0][3], 2.5)
        self.assertEqual(sheet.cell(row=HEADER_ROW + 1, column=3).number_format, "#,##0.00")
        self.assertEqual(sheet.cell(row=HEADER_ROW + 1, column=4).number_format, "#,##0.0##")

    def test_whole_quantities_have_no_trailing_dot_format(self):
        sheet, _, rows = read_sheet(self.build([["Chips", None, "1", "1440"]]))
        self.assertEqual(rows[0][3], 1440)
        self.assertEqual(sheet.cell(row=HEADER_ROW + 1, column=4).number_format, "#,##0")

    def test_codes_keep_digits_and_leading_zeros(self):
        sheet, _, rows = read_sheet(self.build([["Delhi Store", "919820098200", None, None]],
                                               [Column("Name"), Column("Phone"), Column("Amount", MONEY), Column("Qty", QUANTITY)]))
        self.assertEqual(rows[0][1], "919820098200")
        response = xlsx_response(title="Codes", columns=[Column("State code"), Column("Pincode")], rows=[["07", "011001"]], filename="c.xlsx")
        sheet, _, rows = read_sheet(response)
        self.assertEqual(rows[0], ["07", "011001"])
        self.assertEqual(sheet.cell(row=HEADER_ROW + 1, column=1).number_format, "@")

    def test_flattening_unicode_and_layout(self):
        self.assertEqual(flatten_text("Shop 4,\r\nMarket Road\n\nPune "), "Shop 4,, Market Road, Pune")
        self.assertEqual(flatten_text("bad\x07char"), "badchar")  # control chars Excel rejects
        response = self.build([["शर्मा किराना ₹", None, "10", "1"]])
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="t.xlsx"')
        sheet, headers, rows = read_sheet(response)
        self.assertEqual(headers, ["Name", "Phone", "Amount", "Qty"])
        self.assertEqual(rows[0][0], "शर्मा किराना ₹")
        self.assertIsNone(rows[0][1])
        self.assertEqual(sheet["A1"].value, "Test")
        self.assertIn("IST", sheet["A2"].value)
        self.assertEqual(sheet.freeze_panes, f"A{HEADER_ROW + 1}")
        self.assertEqual(sheet.auto_filter.ref, f"A{HEADER_ROW}:D{HEADER_ROW + 1}")
        with self.assertRaises(ValueError):
            self.build([["only one cell"]])


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

        cls.chips = product("Banana Chips", "CH-1", Decimal("120"), catalogue_category=cls.category, mrp=Decimal("10.00"))
        # Same name, different pack: only the MRP tells them apart.
        cls.chips_small = product("Banana Chips", "CH-5", Decimal("30"), mrp=Decimal("5.00"))
        cls.mix = product("=Mixture", "CH-2", Decimal("40"))
        cls.archived = product("Old Namkeen", "CH-3", Decimal("5"), is_active=False)
        cls.empty = product("Sold Out", "CH-4", Decimal("0"))
        for p in (cls.chips, cls.chips_small, cls.mix, cls.archived, cls.empty):
            ensure_inventory_balance(product=p)
        adjust_inventory(product=cls.chips, quantity_delta=Decimal("12.5"), movement_type=StockLedger.ADJUSTMENT, unit_cost=Decimal("7.50"), warehouse=cls.godown)

    def client_as(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def expected_rows(self, **filters):
        """Independent per-product totals from the same row builder."""
        totals = {}
        for balance in _inventory_valuation_rows(**filters):
            p = balance.product
            key = (p.name.lower(), p.mrp is None, p.mrp or 0, p.pk)
            name, mrp, quantity, unit = totals.get(key, (p.name, p.mrp, Decimal("0"), p.base_unit))
            totals[key] = (name, mrp, quantity + balance.quantity_on_hand, unit)
        for p in _legacy_inventory_products(**filters):
            totals[(p.name.lower(), p.mrp is None, p.mrp or 0, p.pk)] = (p.name, p.mrp, p.current_stock, p.base_unit)
        return [
            [name, float(mrp) if mrp is not None else None, float(quantity), unit]
            for _, (name, mrp, quantity, unit) in sorted(totals.items())
        ]

    def test_staff_gets_workbook_matching_row_builder(self):
        response = self.client_as(self.staff).get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["Content-Disposition"], r'attachment; filename="stockbill-inventory-\d{8}-\d{4}\.xlsx"')
        sheet, headers, rows = read_sheet(response)
        self.assertEqual(headers, INVENTORY_HEADERS)
        self.assertEqual(rows, self.expected_rows(warehouse=None, category=None, is_active=None, search=""))
        names = [r[0] for r in rows]
        self.assertIn("Banana Chips", names)
        self.assertNotIn("Sold Out", names)  # zero stock is not "stock left"
        self.assertEqual(sheet["A1"].value, "Inventory stock")

    def test_quantity_total_matches_stock_valuation_report(self):
        _, _, rows = read_sheet(self.client_as(self.staff).get(self.URL))
        screen = self.client_as(self.staff).get("/api/reports/inventory/").data
        self.assertEqual(Decimal(str(sum(r[2] for r in rows))), Decimal(screen["quantity_on_hand"]))

    def test_one_row_per_product_summed_across_warehouses(self):
        _, headers, rows = read_sheet(self.client_as(self.staff).get(self.URL, {"search": "banana"}))
        # ₹10 pack: 120 in Main Warehouse + 12.5 in Godown 2, as one row.
        # ₹5 pack has the same name; MRP keeps them apart, lower MRP first.
        self.assertEqual(rows, [["Banana Chips", 5, 30, "piece"], ["Banana Chips", 10, 132.5, "piece"]])
        self.assertFalse({"SKU", "Brand", "Category", "Warehouse", "Average cost", "Stock value"} & set(headers))

    def test_warehouse_filter_gives_that_warehouse_quantity(self):
        _, _, rows = read_sheet(self.client_as(self.staff).get(self.URL, {"warehouse": str(self.godown.pk)}))
        self.assertEqual(rows, [["Banana Chips", 10, 12.5, "piece"]])

    def test_inventory_page_filters(self):
        # The Inventory page sends warehouse and search; the API also keeps category / is_active.
        for params, filters in [
            ({"warehouse": str(self.godown.pk)}, {"warehouse": self.godown, "category": None, "is_active": None, "search": ""}),
            ({"search": "ch-1"}, {"warehouse": None, "category": None, "is_active": None, "search": "ch-1"}),
            ({"is_active": "false"}, {"warehouse": None, "category": None, "is_active": False, "search": ""}),
            ({"category": str(self.category.pk)}, {"warehouse": None, "category": self.category, "is_active": None, "search": ""}),
        ]:
            _, _, rows = read_sheet(self.client_as(self.staff).get(self.URL, params))
            self.assertEqual(rows, self.expected_rows(**filters), params)
        sheet, _, _ = read_sheet(self.client_as(self.staff).get(self.URL, {"warehouse": str(self.godown.pk), "search": "chips"}))
        self.assertIn("Warehouse: Godown 2", sheet["A2"].value)
        self.assertIn("Search: chips", sheet["A2"].value)

    def test_formula_like_product_name_is_text(self):
        sheet, _, rows = read_sheet(self.client_as(self.staff).get(self.URL, {"search": "CH-2"}))
        self.assertEqual(rows, [["=Mixture", None, 40, "piece"]])
        self.assertEqual(sheet.cell(row=HEADER_ROW + 1, column=1).data_type, "s")

    def test_bad_filter_and_permissions(self):
        self.assertEqual(self.client_as(self.staff).get(self.URL, {"warehouse": "abc"}).status_code, 400)
        self.assertEqual(self.client_as(self.admin).get(self.URL).status_code, 200)
        self.assertIn(self.client_as(None).get(self.URL).status_code, {401, 403})
