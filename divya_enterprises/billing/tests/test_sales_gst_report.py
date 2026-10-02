"""Comprehensive test suite for the invoice-level Sales GST Report and Excel export.

Validates all 33 required audit scenarios:
- Exact 10 target columns
- POSTED-only invoice inclusion (DRAFT and CANCELLED excluded)
- Whole-rupee BILL AMT. display rounding via round_inr (Decimal ROUND_HALF_UP)
- Exact R.OFF math: display_bill_amt - (taxable + tax + sur + tax_free + exempted)
- Invariant: TOTAL BILL AMT. = TOTAL TAXABLE + TOTAL TAX + TOTAL SUR. + TOTAL TAX FREE + TOTAL EXEMPTED + TOTAL R.OFF
- Positive, negative, and zero round-off cases
- Immutable customer snapshots (survives customer master edits and walk-in)
- Date range filtering (inclusive calendar dates, invalid date rejection)
- Openpyxl Excel export (HTTP 200, MIME type, filename, cell formatting, formula totals)
- Role-based authorization (staff/admin allowed, unauthenticated rejected)
"""

import datetime
from decimal import Decimal
import io
import openpyxl

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from billing.reports import build_sales_gst_report_xlsx, get_sales_gst_report_data
from customers.models import Customer
from inventory.models import InventoryBalance, Product, TaxRate
from inventory.services import get_default_warehouse

User = get_user_model()


class SalesGstReportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="gst-admin", password="AdminPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="gst-staff", password="StaffPass123!", role="staff"
        )
        cls.regular_user = User.objects.create_user(
            username="gst-regular", password="UserPass123!", role="customer"
        )

        cls.seller = BusinessProfile.objects.create(
            business_name="DIVYA ENTERPRISES",
            trade_name="DIVYA ENTERPRISES",
            gstin="27DIVYA1234A1Z5",
            registered_address="Shop 1, Main Road, Mumbai, Maharashtra 400097",
            state="Maharashtra",
            state_code="27",
            phone="9876543210",
        )

        cls.tax_5, _ = TaxRate.objects.get_or_create(
            name="GST 5%", defaults={"rate": Decimal("5.00")}
        )
        cls.tax_18, _ = TaxRate.objects.get_or_create(
            name="GST 18%", defaults={"rate": Decimal("18.00")}
        )

        cls.warehouse = get_default_warehouse()

        cls.customer_alpha = Customer.objects.create(
            name="ALPHA ENTERPRISES",
            state="Maharashtra",
            state_code="27",
            gstin="27AAAAA1111A1Z1",
            credit_limit=Decimal("500000.00"),
        )
        cls.customer_beta = Customer.objects.create(
            name="BETA STORES",
            state="Maharashtra",
            state_code="27",
            gstin="27BBBBB2222B1Z2",
            credit_limit=Decimal("500000.00"),
        )

        cls.product_chips = Product.objects.create(
            name="Yellow Banana Chips 200g",
            sku="YBC-200",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=Decimal("50.00"),
            cost_price=Decimal("35.00"),
            tax=cls.tax_5,
            current_stock=1000,
        )
        cls.product_nuts = Product.objects.create(
            name="Salted Peanuts 100g",
            sku="SPN-100",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=Decimal("20.00"),
            cost_price=Decimal("12.00"),
            tax=cls.tax_18,
            current_stock=1000,
        )

    def _create_direct_invoice(self, *, number, date_str, customer, state, total_amt, lines, customer_snapshot=None, customer_gstin_snapshot=None):
        """Helper to create an invoice directly with exact line snapshots for deterministic testing."""
        inv_date = datetime.date.fromisoformat(date_str)
        inv = Invoice.objects.create(
            invoice_number=number,
            customer=customer,
            customer_name_snapshot=customer_snapshot if customer_snapshot is not None else (customer.name if customer else "Walk-in customer"),
            customer_gstin_snapshot=customer_gstin_snapshot if customer_gstin_snapshot is not None else ((customer.gstin or "") if customer else ""),
            state=state,
            total_amount=Decimal(str(total_amt)),
            seller_business_name_snapshot=self.seller.business_name,
            seller_gstin_snapshot=self.seller.gstin,
        )
        Invoice.objects.filter(pk=inv.pk).update(invoice_date=inv_date)
        inv.refresh_from_db()
        for line in lines:
            tax_val = Decimal(str(line.get("tax", "0.00")))
            cgst_default = (tax_val / Decimal("2")).quantize(Decimal("0.01"))
            sgst_default = tax_val - cgst_default
            InvoiceLineItem.objects.create(
                invoice=inv,
                product=line["product"],
                quantity=Decimal(str(line.get("quantity", 1))),
                base_quantity=Decimal(str(line.get("quantity", 1))),
                taxable_value_snapshot=Decimal(str(line["taxable"])),
                tax_rate=Decimal(str(line.get("tax_rate", 5.00))),
                cgst_rate=Decimal(str(line.get("cgst_rate", 2.50))),
                cgst_amount=Decimal(str(line.get("cgst", cgst_default))),
                sgst_rate=Decimal(str(line.get("sgst_rate", 2.50))),
                sgst_amount=Decimal(str(line.get("sgst", sgst_default))),
                igst_rate=Decimal(str(line.get("igst_rate", 0.00))),
                igst_amount=Decimal(str(line.get("igst", 0.00))),
                tax_amount=tax_val,
                line_total=Decimal(str(line["line_total"])),
                rate_charged=Decimal(str(line["taxable"])),
                product_name_snapshot=line["product"].name,
                hsn_sac_snapshot=line.get("hsn", "21069099"),
            )
        return inv

    def test_01_one_posted_invoice(self):
        """1. One posted invoice renders with exact line totals and whole-rupee display amount."""
        # Invoice: Taxable 2203.80, Tax 396.70 -> sum = 2600.50 -> rounded bill_amt = 2601.00, r_off = +0.50
        self._create_direct_invoice(
            number="A000001",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="2600.50",
            lines=[
                {
                    "product": self.product_chips,
                    "taxable": "2203.80",
                    "tax": "396.70",
                    "cgst": "198.35",
                    "sgst": "198.35",
                    "line_total": "2600.50",
                    "hsn": "21069099",
                }
            ],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["date"], "10-08-2026")
        self.assertEqual(row["bill_no"], "A000001")
        self.assertEqual(row["party_name"], "ALPHA ENTERPRISES")
        self.assertEqual(row["gstin"], "27AAAAA1111A1Z1")
        self.assertEqual(row["hsn"], "21069099")
        self.assertEqual(row["bill_amt"], "2601.00")
        self.assertEqual(row["taxable"], "2203.80")
        self.assertEqual(row["tax"], "396.70")
        self.assertEqual(row["sgst"], "198.35")
        self.assertEqual(row["cgst"], "198.35")
        self.assertEqual(row["igst"], "0.00")
        self.assertEqual(row["total_gst"], "396.70")
        self.assertEqual(row["sur"], "0.00")
        self.assertEqual(row["tax_free"], "0.00")
        self.assertEqual(row["exempted"], "0.00")
        self.assertEqual(row["r_off"], "0.50")
        self.assertEqual(data["totals"]["sgst"], "198.35")
        self.assertEqual(data["totals"]["cgst"], "198.35")
        self.assertEqual(data["totals"]["igst"], "0.00")
        self.assertEqual(data["totals"]["total_gst"], "396.70")

    def test_02_multiple_posted_invoices_and_granularity(self):
        """2 & 5. Multiple posted invoices produce exactly one row per invoice, sorted by date then bill number."""
        self._create_direct_invoice(
            number="A000002",
            date_str="2026-08-12",
            customer=self.customer_beta,
            state=Invoice.STATE_POSTED,
            total_amt="1000.00",
            lines=[{"product": self.product_nuts, "taxable": "847.46", "tax": "152.54", "line_total": "1000.00"}],
        )
        self._create_direct_invoice(
            number="A000001",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="500.00",
            lines=[{"product": self.product_chips, "taxable": "476.19", "tax": "23.81", "line_total": "500.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))
        self.assertEqual(len(data["rows"]), 2)
        # Check ordering: 10-08-2026 comes before 12-08-2026
        self.assertEqual(data["rows"][0]["bill_no"], "A000001")
        self.assertEqual(data["rows"][1]["bill_no"], "A000002")

    def test_03_and_04_date_filtering_inclusive(self):
        """3 & 4. Filter is calendar inclusive on from and to dates; invoices outside the window are excluded."""
        self._create_direct_invoice(
            number="EARLY",
            date_str="2026-07-31",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )
        self._create_direct_invoice(
            number="ON_FROM",
            date_str="2026-08-01",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )
        self._create_direct_invoice(
            number="ON_TO",
            date_str="2026-08-15",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )
        self._create_direct_invoice(
            number="LATE",
            date_str="2026-08-16",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 1), datetime.date(2026, 8, 15))
        bill_nos = [r["bill_no"] for r in data["rows"]]
        self.assertEqual(bill_nos, ["ON_FROM", "ON_TO"])

    def test_06_to_10_columns_and_aggregations(self):
        """6, 7, 8, 9, 10. Multi-line invoice aggregates taxable and tax correctly across lines."""
        # 2 lines: line 1 = taxable 100, tax 5. Line 2 = taxable 200, tax 36. Total taxable = 300, total tax = 41. Total = 341.00.
        self._create_direct_invoice(
            number="MULTI-01",
            date_str="2026-08-20",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="341.00",
            lines=[
                {"product": self.product_chips, "taxable": "100.00", "tax": "5.00", "cgst": "2.50", "sgst": "2.50", "line_total": "105.00"},
                {"product": self.product_nuts, "taxable": "200.00", "tax": "36.00", "cgst": "18.00", "sgst": "18.00", "line_total": "236.00"},
            ],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 20), datetime.date(2026, 8, 20))
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["date"], "20-08-2026")
        self.assertEqual(row["bill_no"], "MULTI-01")
        self.assertEqual(row["party_name"], "ALPHA ENTERPRISES")
        self.assertEqual(row["bill_amt"], "341.00")
        self.assertEqual(row["taxable"], "300.00")
        self.assertEqual(row["tax"], "41.00")
        self.assertEqual(row["r_off"], "0.00")

    def test_11_tax_equals_cgst_sgst_igst(self):
        """11. Tax field is identically equal to the sum of line item taxes."""
        inv = self._create_direct_invoice(
            number="SPLIT-01",
            date_str="2026-08-11",
            customer=self.customer_beta,
            state=Invoice.STATE_POSTED,
            total_amt="236.00",
            lines=[
                {"product": self.product_nuts, "taxable": "200.00", "tax": "36.00", "cgst": "18.00", "sgst": "18.00", "line_total": "236.00"}
            ],
        )
        line = inv.line_items.first()
        self.assertEqual(line.tax_amount, line.cgst_amount + line.sgst_amount + line.igst_amount)

        data = get_sales_gst_report_data(datetime.date(2026, 8, 11), datetime.date(2026, 8, 11))
        self.assertEqual(data["rows"][0]["tax"], "36.00")

    def test_12_13_14_sur_tax_free_exempted_zero(self):
        """12, 13, 14. SUR., TAX FREE, and EXEMPTED always display 0.00."""
        self._create_direct_invoice(
            number="ZERO-COLS",
            date_str="2026-08-14",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 14), datetime.date(2026, 8, 14))
        row = data["rows"][0]
        self.assertEqual(row["sur"], "0.00")
        self.assertEqual(row["tax_free"], "0.00")
        self.assertEqual(row["exempted"], "0.00")

    def test_15_positive_round_off(self):
        """15. Positive R.OFF: total_amount 2600.50 -> rounded 2601.00 -> R.OFF = +0.50."""
        self._create_direct_invoice(
            number="POS-ROFF",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="2600.50",
            lines=[{"product": self.product_chips, "taxable": "2203.80", "tax": "396.70", "line_total": "2600.50"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 10), datetime.date(2026, 8, 10))
        row = data["rows"][0]
        self.assertEqual(row["bill_amt"], "2601.00")
        self.assertEqual(row["r_off"], "0.50")

    def test_16_negative_round_off(self):
        """16. Negative R.OFF: total_amount 625.12 -> rounded 625.00 -> R.OFF = -0.12."""
        self._create_direct_invoice(
            number="NEG-ROFF",
            date_str="2026-08-16",
            customer=self.customer_beta,
            state=Invoice.STATE_POSTED,
            total_amt="625.12",
            lines=[{"product": self.product_chips, "taxable": "583.00", "tax": "42.12", "line_total": "625.12"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 16), datetime.date(2026, 8, 16))
        row = data["rows"][0]
        self.assertEqual(row["bill_amt"], "625.00")
        self.assertEqual(row["r_off"], "-0.12")

    def test_17_zero_round_off(self):
        """17. Zero R.OFF: total_amount 864.00 -> rounded 864.00 -> R.OFF = 0.00."""
        self._create_direct_invoice(
            number="ZERO-ROFF",
            date_str="2026-08-15",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="864.00",
            lines=[{"product": self.product_chips, "taxable": "732.20", "tax": "131.80", "line_total": "864.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 15), datetime.date(2026, 8, 15))
        row = data["rows"][0]
        self.assertEqual(row["bill_amt"], "864.00")
        self.assertEqual(row["r_off"], "0.00")

    def test_18_whole_rupee_bill_amt(self):
        """18. Every bill amount in rows has whole-rupee format ending in .00."""
        self._create_direct_invoice(
            number="INTRUPEE-01",
            date_str="2026-08-18",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="918.80",
            lines=[{"product": self.product_chips, "taxable": "874.80", "tax": "44.00", "line_total": "918.80"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 18), datetime.date(2026, 8, 18))
        row = data["rows"][0]
        self.assertEqual(row["bill_amt"], "919.00")
        self.assertTrue(row["bill_amt"].endswith(".00"))

    def test_19_totals_reconciliation_invariant(self):
        """19. Mathematical invariant: TOTAL BILL AMT = TOTAL TAXABLE + TOTAL TAX + TOTAL R.OFF."""
        # 1. Positive R.OFF: 2600.50 -> 2601.00 (+0.50)
        self._create_direct_invoice(
            number="INV-A",
            date_str="2026-08-20",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="2600.50",
            lines=[{"product": self.product_chips, "taxable": "2203.80", "tax": "396.70", "line_total": "2600.50"}],
        )
        # 2. Negative R.OFF: 625.12 -> 625.00 (-0.12)
        self._create_direct_invoice(
            number="INV-B",
            date_str="2026-08-21",
            customer=self.customer_beta,
            state=Invoice.STATE_POSTED,
            total_amt="625.12",
            lines=[{"product": self.product_chips, "taxable": "583.00", "tax": "42.12", "line_total": "625.12"}],
        )
        # 3. Zero R.OFF: 864.00 -> 864.00 (0.00)
        self._create_direct_invoice(
            number="INV-C",
            date_str="2026-08-22",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="864.00",
            lines=[{"product": self.product_chips, "taxable": "732.20", "tax": "131.80", "line_total": "864.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 20), datetime.date(2026, 8, 25))
        totals = data["totals"]
        self.assertEqual(totals["invoice_count"], 3)

        b = Decimal(totals["bill_amt"])
        t = Decimal(totals["taxable"])
        tx = Decimal(totals["tax"])
        s = Decimal(totals["sur"])
        tf = Decimal(totals["tax_free"])
        ex = Decimal(totals["exempted"])
        ro = Decimal(totals["r_off"])

        self.assertEqual(b, t + tx + s + tf + ex + ro)
        self.assertEqual(totals["bill_amt"], "4090.00")
        self.assertEqual(totals["taxable"], "3519.00")
        self.assertEqual(totals["tax"], "570.62")
        self.assertEqual(totals["r_off"], "0.38")

    def test_20_and_21_draft_and_cancelled_excluded(self):
        """20 & 21. DRAFT and CANCELLED invoices are strictly excluded."""
        self._create_direct_invoice(
            number="DRAFT-01",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_DRAFT,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )
        self._create_direct_invoice(
            number="CANCELLED-01",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_CANCELLED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )
        self._create_direct_invoice(
            number="POSTED-01",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 10), datetime.date(2026, 8, 10))
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["bill_no"], "POSTED-01")

    def test_22_walk_in_customer(self):
        """22. Customer null invoices display 'Walk-in customer' party name."""
        self._create_direct_invoice(
            number="WALKIN-01",
            date_str="2026-08-15",
            customer=None,
            state=Invoice.STATE_POSTED,
            total_amt="200.00",
            lines=[{"product": self.product_chips, "taxable": "190.48", "tax": "9.52", "line_total": "200.00"}],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 15), datetime.date(2026, 8, 15))
        self.assertEqual(data["rows"][0]["party_name"], "Walk-in customer")

    def test_23_historical_customer_snapshot(self):
        """23. Historical invoice party name does not change when master customer record changes."""
        cust = Customer.objects.create(name="ORIGINAL NAME", state_code="27")
        self._create_direct_invoice(
            number="HIST-01",
            date_str="2026-08-17",
            customer=cust,
            state=Invoice.STATE_POSTED,
            total_amt="100.00",
            customer_snapshot="ORIGINAL NAME",
            lines=[{"product": self.product_chips, "taxable": "95.24", "tax": "4.76", "line_total": "100.00"}],
        )

        # Mutate master customer record
        cust.name = "NEW MUTATED NAME"
        cust.save()

        data = get_sales_gst_report_data(datetime.date(2026, 8, 17), datetime.date(2026, 8, 17))
        self.assertEqual(data["rows"][0]["party_name"], "ORIGINAL NAME")

    def test_24_permissions_staff_admin_unauthenticated(self):
        """24. Authorization: Staff and Admin have access; unauthenticated user is rejected."""
        url = "/api/reports/sales-gst/?from=2026-08-01&to=2026-08-31"

        # Anonymous
        res_anon = self.client.get(url)
        self.assertIn(res_anon.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

        # Regular non-staff user
        self.client.force_authenticate(user=self.regular_user)
        res_reg = self.client.get(url)
        self.assertEqual(res_reg.status_code, status.HTTP_403_FORBIDDEN)

        # Staff user
        self.client.force_authenticate(user=self.staff)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, status.HTTP_200_OK)

        # Admin user
        self.client.force_authenticate(user=self.admin)
        res_admin = self.client.get(url)
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)

    def test_25_empty_result(self):
        """25. Empty result for a period with no posted invoices returns clean 0.00 totals."""
        data = get_sales_gst_report_data(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["totals"]["invoice_count"], 0)
        self.assertEqual(data["totals"]["bill_amt"], "0.00")
        self.assertEqual(data["totals"]["taxable"], "0.00")
        self.assertEqual(data["totals"]["tax"], "0.00")
        self.assertEqual(data["totals"]["r_off"], "0.00")

    def test_26_invalid_dates(self):
        """26. Invalid date formats, missing params, and from > to return HTTP 400."""
        self.client.force_authenticate(user=self.staff)

        # Missing params
        res1 = self.client.get("/api/reports/sales-gst/")
        self.assertEqual(res1.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid date format
        res2 = self.client.get("/api/reports/sales-gst/?from=10-08-2026&to=2026-08-31")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)

        # from > to
        res3 = self.client.get("/api/reports/sales-gst/?from=2026-08-31&to=2026-08-01")
        self.assertEqual(res3.status_code, status.HTTP_400_BAD_REQUEST)

    def test_27_to_32_excel_export_and_workbook_structure(self):
        """27 to 32. Excel export endpoint returns valid XLSX workbook with exact formatting, headers, and formulas."""
        self._create_direct_invoice(
            number="XL-001",
            date_str="2026-08-10",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="2600.50",
            lines=[{"product": self.product_chips, "taxable": "2203.80", "tax": "396.70", "line_total": "2600.50"}],
        )

        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/reports/sales-gst/export/?from=2026-08-01&to=2026-08-31")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("sales-gst-report-20260801-20260831.xlsx", res["Content-Disposition"])

        # Inspect XLSX byte content
        wb = openpyxl.load_workbook(io.BytesIO(res.content), data_only=False)
        self.assertIn("Sales GST Report", wb.sheetnames)
        ws = wb["Sales GST Report"]

        # Check titles
        self.assertEqual(ws["A1"].value, "DIVYA ENTERPRISES")
        self.assertEqual(ws["A2"].value, "SALES GST REPORT")
        self.assertEqual(ws["A3"].value, "Period: 01-08-2026 to 31-08-2026")

        # Check Row 5 headers (16 columns, centered)
        expected_headers = [
            "DATE",
            "BILL NO.",
            "PARTY NAME",
            "GSTIN",
            "HSN",
            "BILL AMT.",
            "TAXABLE",
            "TAX",
            "SGST",
            "CGST",
            "IGST",
            "TOTAL GST",
            "SUR.",
            "TAX FREE",
            "EXEMPTED",
            "R.OFF",
        ]
        actual_headers = [ws.cell(row=5, column=col).value for col in range(1, 17)]
        self.assertEqual(actual_headers, expected_headers)

        # Check header alignment (all centered horizontally & vertically)
        for col in range(1, 17):
            align = ws.cell(row=5, column=col).alignment
            self.assertEqual(align.horizontal, "center")
            self.assertEqual(align.vertical, "center")

        # Check Data Row 6
        self.assertEqual(ws.cell(row=6, column=2).value, "XL-001")
        self.assertEqual(ws.cell(row=6, column=3).value, "ALPHA ENTERPRISES")
        self.assertEqual(ws.cell(row=6, column=4).value, "27AAAAA1111A1Z1")
        self.assertEqual(ws.cell(row=6, column=5).value, "21069099")
        self.assertEqual(ws.cell(row=6, column=6).value, 2601.00)
        self.assertEqual(ws.cell(row=6, column=7).value, 2203.80)
        self.assertEqual(ws.cell(row=6, column=8).value, 396.70)
        self.assertEqual(ws.cell(row=6, column=9).value, 198.35)
        self.assertEqual(ws.cell(row=6, column=10).value, 198.35)
        self.assertEqual(ws.cell(row=6, column=11).value, 0.00)
        self.assertEqual(ws.cell(row=6, column=12).value, 396.70)
        self.assertEqual(ws.cell(row=6, column=16).value, 0.50)

        # Check formatting of numbers (right-aligned, currency format)
        self.assertEqual(ws.cell(row=6, column=6).number_format, "#,##0.00")
        self.assertEqual(ws.cell(row=6, column=6).alignment.horizontal, "right")

        # Check Total Row (Row 7)
        self.assertEqual(ws.cell(row=7, column=1).value, "TOTAL")
        self.assertEqual(ws.cell(row=7, column=6).value, "=SUM(F6:F6)")
        self.assertEqual(ws.cell(row=7, column=7).value, "=SUM(G6:G6)")
        self.assertEqual(ws.cell(row=7, column=8).value, "=SUM(H6:H6)")
        self.assertEqual(ws.cell(row=7, column=9).value, "=SUM(I6:I6)")
        self.assertEqual(ws.cell(row=7, column=10).value, "=SUM(J6:J6)")
        self.assertEqual(ws.cell(row=7, column=11).value, "=SUM(K6:K6)")
        self.assertEqual(ws.cell(row=7, column=12).value, "=SUM(L6:L6)")
        self.assertEqual(ws.cell(row=7, column=16).value, "=SUM(P6:P6)")

    def test_33_report_and_print_data_consistency(self):
        """33. Report API data contains all required elements for browser and print rendering."""
        self._create_direct_invoice(
            number="PRINT-01",
            date_str="2026-08-25",
            customer=self.customer_beta,
            state=Invoice.STATE_POSTED,
            total_amt="1000.00",
            lines=[{"product": self.product_nuts, "taxable": "847.46", "tax": "152.54", "line_total": "1000.00"}],
        )

        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/reports/sales-gst/?from=2026-08-01&to=2026-08-31")
        data = res.json()

        self.assertIn("columns", data)
        self.assertIn("rows", data)
        self.assertIn("totals", data)
        self.assertIn("seller", data)
        self.assertEqual(data["seller"]["business_name"], "DIVYA ENTERPRISES")
        self.assertEqual(data["columns"], [
            "DATE",
            "BILL NO.",
            "PARTY NAME",
            "GSTIN",
            "HSN",
            "BILL AMT.",
            "TAXABLE",
            "TAX",
            "SGST",
            "CGST",
            "IGST",
            "TOTAL GST",
            "SUR.",
            "TAX FREE",
            "EXEMPTED",
            "R.OFF",
        ])
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["totals"]["bill_amt"], "1000.00")

    def test_34_gst_components_and_total_gst_math(self):
        """34. SGST/CGST/IGST breakdown and TOTAL GST = SGST + CGST + IGST formula."""
        # Inter-state invoice with IGST only
        self._create_direct_invoice(
            number="INTER-01",
            date_str="2026-08-18",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="1180.00",
            lines=[
                {
                    "product": self.product_nuts,
                    "taxable": "1000.00",
                    "tax": "180.00",
                    "cgst": "0.00",
                    "sgst": "0.00",
                    "igst_rate": "18.00",
                    "igst": "180.00",
                    "line_total": "1180.00",
                    "hsn": "20081990",
                }
            ],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 18), datetime.date(2026, 8, 18))
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["sgst"], "0.00")
        self.assertEqual(row["cgst"], "0.00")
        self.assertEqual(row["igst"], "180.00")
        self.assertEqual(row["total_gst"], "180.00")
        self.assertEqual(row["hsn"], "20081990")

    def test_35_distinct_line_hsns_comma_separated(self):
        """35. Multi-product invoice with distinct HSNs joins them sorted and comma-separated."""
        self._create_direct_invoice(
            number="MULTI-HSN",
            date_str="2026-08-22",
            customer=self.customer_alpha,
            state=Invoice.STATE_POSTED,
            total_amt="2000.00",
            lines=[
                {"product": self.product_chips, "taxable": "900.00", "tax": "100.00", "line_total": "1000.00", "hsn": "21069099"},
                {"product": self.product_nuts, "taxable": "900.00", "tax": "100.00", "line_total": "1000.00", "hsn": "08013200"},
            ],
        )

        data = get_sales_gst_report_data(datetime.date(2026, 8, 22), datetime.date(2026, 8, 22))
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["hsn"], "08013200, 21069099")

    def test_36_historical_snapshot_immutability(self):
        """36. Report values use snapshots; customer GSTIN edits do not mutate historical reports."""
        self._create_direct_invoice(
            number="HIST-01",
            date_str="2026-08-24",
            customer=self.customer_alpha,
            customer_snapshot="ALPHA ORIGINAL NAME",
            customer_gstin_snapshot="27ORIGINALGSTIN1Z",
            state=Invoice.STATE_POSTED,
            total_amt="500.00",
            lines=[{"product": self.product_chips, "taxable": "476.19", "tax": "23.81", "line_total": "500.00", "hsn": "21069099"}],
        )

        # Mutate customer master record
        self.customer_alpha.name = "ALPHA MODIFIED NAME"
        self.customer_alpha.gstin = "27MODIFIEDGST1Z"
        self.customer_alpha.save()

        data = get_sales_gst_report_data(datetime.date(2026, 8, 24), datetime.date(2026, 8, 24))
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["party_name"], "ALPHA ORIGINAL NAME")
        self.assertEqual(row["gstin"], "27ORIGINALGSTIN1Z")

    def test_37_item_summary_excel_alignment_and_formatting(self):
        """37. Item-wise summary Excel export has horizontally/vertically centered headers and proper widths."""
        from billing.services import build_item_summary_xlsx

        summary_data = {
            "selected_invoice_numbers": ["INV-001", "INV-002"],
            "total_products": 2,
            "total_base_quantity": "50.000",
            "items": [
                {
                    "product_id": 1,
                    "product_name": "Yellow Banana Chips 200g",
                    "sku": "YBC-200",
                    "variant_summary": "Standard",
                    "mrp": "50.00",
                    "total_base_quantity": "30.000",
                    "base_unit": "piece",
                    "invoice_count": 2,
                },
                {
                    "product_id": 2,
                    "product_name": "Salted Peanuts 100g",
                    "sku": "SPN-100",
                    "variant_summary": "Standard",
                    "mrp": "20.00",
                    "total_base_quantity": "20.000",
                    "base_unit": "piece",
                    "invoice_count": 1,
                },
            ],
        }

        xlsx_bytes = build_item_summary_xlsx(summary_data)
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
        self.assertIn("Item-wise Summary", wb.sheetnames)
        ws = wb["Item-wise Summary"]

        # Check headers (row 6) - exactly 4 columns
        expected_headers = [
            "#",
            "PRODUCT NAME",
            "MRP",
            "TOTAL QUANTITY",
        ]
        actual_headers = [ws.cell(row=6, column=col).value for col in range(1, 5)]
        self.assertEqual(actual_headers, expected_headers)
        self.assertIsNone(ws.cell(row=6, column=5).value)

        # Verify no legacy columns (SKU, VARIANT / PACK, BASE QTY, INVOICES)
        all_row6_values = [str(ws.cell(row=6, column=col).value).upper() for col in range(1, 10) if ws.cell(row=6, column=col).value]
        for unexpected in ["SKU", "VARIANT / PACK", "VARIANT", "PACK", "BASE QTY", "BASE UNIT", "INVOICES", "INVOICE COUNT"]:
            self.assertNotIn(unexpected, all_row6_values)

        # All 4 headers must be horizontally AND vertically centered without text wrapping
        for col in range(1, 5):
            align = ws.cell(row=6, column=col).alignment
            self.assertEqual(align.horizontal, "center")
            self.assertEqual(align.vertical, "center")
            self.assertFalse(align.wrap_text)

        # Check data row alignments and number formatting
        row7_idx = ws.cell(row=7, column=1)
        self.assertEqual(row7_idx.value, 1)
        self.assertEqual(row7_idx.alignment.horizontal, "center")

        row7_prod = ws.cell(row=7, column=2)
        self.assertEqual(row7_prod.value, "Yellow Banana Chips 200g")
        self.assertEqual(row7_prod.alignment.horizontal, "left")

        row7_mrp = ws.cell(row=7, column=3)
        self.assertEqual(row7_mrp.alignment.horizontal, "right")
        self.assertEqual(row7_mrp.number_format, '"₹"#,##0.00')

        row7_qty = ws.cell(row=7, column=4)
        self.assertEqual(row7_qty.alignment.horizontal, "right")

        # Check column dimensions
        self.assertGreaterEqual(ws.column_dimensions["A"].width, 6)
        self.assertGreaterEqual(ws.column_dimensions["B"].width, 40)
        self.assertGreaterEqual(ws.column_dimensions["C"].width, 12)
        self.assertGreaterEqual(ws.column_dimensions["D"].width, 20)

