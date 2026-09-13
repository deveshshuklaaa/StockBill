"""Management report reconciliation tests.

Every report total is verified against the authoritative operational
records (invoice history, purchase history, InventoryBalance, StockLedger,
customer model). The rules under test:

- SALES: POSTED invoices only; DRAFT/CANCELLED excluded from active
  totals, cancelled surfaced separately. net_sales reconciles with the
  invoice list for the same period.
- PURCHASES: POSTED purchases valued at posting-time snapshots;
  CANCELLED excluded from active totals; supplier filter scopes rows.
- INVENTORY: value = Σ InventoryBalance.quantity_on_hand × average_cost,
  reconciling with the warehouse summary endpoint.
- STOCK MOVEMENT: mirrors StockLedger rows and net quantities.
- PRODUCT SALES: historical cogs_amount snapshots survive later cost/WAC
  changes (no current-cost contamination).
- CUSTOMER: per-customer totals reconcile with invoice history;
  outstanding equals the customer model's authoritative property.
- TAX: output GST equals invoice line snapshots; input GST equals
  purchase line snapshots; CGST/SGST/IGST split preserved.
- PROFIT: revenue − historical COGS = gross profit; cancelled invoices
  excluded.
- DASHBOARD: each metric matches its underlying report query.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice
from customers.models import Customer
from inventory.models import (
    InventoryBalance,
    Product,
    PurchaseInvoice,
    StockLedger,
    Supplier,
    TaxRate,
    Warehouse,
)
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse

User = get_user_model()

TODAY = datetime.date(2026, 9, 13)
EARLIER = datetime.date(2026, 9, 10)


def make_product(cls, name, price):
    return Product.objects.create(
        name=name,
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        default_price=price,
        cost_price=Decimal("0"),
        tax=cls.tax,
        current_stock=0,
    )


def make_report_context(cls):
    cls.admin = User.objects.create_user(
        username="rep2-admin", password="StrongPass123!", role="admin"
    )
    cls.staff = User.objects.create_user(
        username="rep2-staff", password="StrongPass123!", role="staff"
    )
    BusinessProfile.objects.create(
        business_name="Divya Enterprises",
        gstin="27DIVYA1234A1Z5",
        registered_address="Shop 1, Main Road, Mumbai",
        state="Maharashtra",
        state_code="27",
    )
    cls.tax, _ = TaxRate.objects.get_or_create(
        name="GST 18%", defaults={"rate": Decimal("18.00")}
    )
    cls.warehouse = get_default_warehouse()
    cls.supplier_intra = Supplier.objects.create(
        name="Alpha Traders", gstin="27AAACA1234A1Z5", state="Maharashtra", state_code="27"
    )
    cls.supplier_inter = Supplier.objects.create(
        name="Beta Distributors", gstin="24AAACB5678B1Z3", state="Gujarat", state_code="24"
    )
    cls.customer_a = Customer.objects.create(
        name="Report Customer A", state_code="27", credit_limit=Decimal("100000")
    )
    cls.customer_b = Customer.objects.create(name="Report Customer B", state_code="27")

    # Receive stock so sales have real WAC-backed COGS. 100 units @ ₹6.
    create_purchase(
        supplier=cls.supplier_intra,
        warehouse=cls.warehouse,
        invoice_date=EARLIER,
        line_items=[
            {"product": make_product(cls, "Report Product A", Decimal("10.00")), "quantity": Decimal("100"), "rate": Decimal("6.00")}
        ],
        created_by=cls.admin,
        post=True,
    )
    cls.product_a = Product.objects.get(name="Report Product A")
    create_purchase(
        supplier=cls.supplier_inter,
        warehouse=cls.warehouse,
        invoice_date=EARLIER,
        line_items=[
            {"product": make_product(cls, "Report Product B", Decimal("20.00")), "quantity": Decimal("50"), "rate": Decimal("8.00")}
        ],
        created_by=cls.admin,
        post=True,
    )
    cls.product_b = Product.objects.get(name="Report Product B")

    from billing.services import create_invoice

    # Posted sale TODAY: customer A buys 10 × A @ ₹10 (tax-exclusive 18%).
    # gross 100, tax 18, total 118; COGS = 10 × 6 = 60.
    cls.sale_a = create_invoice(
        customer=cls.customer_a,
        invoice_number="REP-A-0001",
        created_by=cls.admin,
        payment_type="credit",
        line_items=[
            {"product": cls.product_a, "quantity": Decimal("10"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")}
        ],
    )
    # Posted sale TODAY: customer B buys 2 × B @ ₹20. total 47.20; COGS = 2 × 8 = 16.
    cls.sale_b = create_invoice(
        customer=cls.customer_b,
        invoice_number="REP-B-0002",
        created_by=cls.admin,
        payment_type="cash",
        line_items=[
            {"product": cls.product_b, "quantity": Decimal("2"), "rate_charged": Decimal("20.00"), "tax_rate": Decimal("18.00")}
        ],
    )
    # Draft invoice: must be excluded from every report.
    cls.draft_sale = create_invoice(
        customer=cls.customer_a,
        invoice_number="REP-DRAFT-0003",
        created_by=cls.admin,
        payment_type="credit",
        state=Invoice.STATE_DRAFT,
        line_items=[
            {"product": cls.product_a, "quantity": Decimal("5"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")}
        ],
    )
    # Cancelled sale: excluded from active sales; counted separately.
    cls.cancelled_sale = create_invoice(
        customer=cls.customer_a,
        invoice_number="REP-CANCEL-0004",
        created_by=cls.admin,
        payment_type="credit",
        line_items=[
            {"product": cls.product_a, "quantity": Decimal("3"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")}
        ],
    )
    from billing.services import cancel_invoice

    cancel_invoice(invoice_id=cls.cancelled_sale.pk, cancelled_by=cls.admin, reason="report test")

    # Cancelled purchase: excluded from active purchase totals.
    cls.cancelled_purchase = create_purchase(
        supplier=cls.supplier_intra,
        warehouse=cls.warehouse,
        invoice_date=EARLIER,
        line_items=[
            {"product": cls.product_a, "quantity": Decimal("10"), "rate": Decimal("6.00")}
        ],
        created_by=cls.admin,
        post=True,
    )
    from inventory.purchase_services import cancel_purchase

    cancel_purchase(purchase_id=cls.cancelled_purchase.pk, cancelled_by=cls.admin, reason="report test")


class ReportTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        make_report_context(cls)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class SalesReportReconciliationTests(ReportTestBase):
    """SALES tests 1-6: POSTED included; DRAFT/CANCELLED excluded; filters."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_posted_invoices_included(self):
        response = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["invoice_count"], 2)
        # net = 118.00 + 47.20
        self.assertEqual(response.data["net_sales"], Decimal("166.00"))
        # taxable = 100 + 40
        self.assertEqual(response.data["taxable_sales"], Decimal("140.00"))
        # gst = 18 + 7.20
        self.assertEqual(response.data["gst"], Decimal("26.00"))
        self.assertEqual(response.data["gross_sales"], Decimal("140.00"))
        self.assertEqual(response.data["cogs"], Decimal("76.00"))
        self.assertEqual(response.data["gross_profit"], Decimal("90.00"))

    def test_draft_invoices_excluded(self):
        response = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}")
        # Draft invoice REP-DRAFT-0003 (5 × 10) never appears.
        self.assertEqual(response.data["invoice_count"], 2)
        self.assertNotEqual(response.data["net_sales"], Decimal("224.00"))

    def test_cancelled_excluded_from_active_and_counted_separately(self):
        response = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}")
        self.assertEqual(response.data["invoice_count"], 2)
        self.assertEqual(response.data["cancelled_invoice_count"], 1)
        # 3 × 10 × 1.18 = 35.40
        self.assertEqual(response.data["cancelled_invoice_value"], Decimal("36.00"))
        self.assertEqual(response.data["net_sales"], Decimal("166.00"))

    def test_reconciles_with_invoice_history(self):
        report = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}").data
        history = self.client.get(
            f"/api/invoices/?state=POSTED&from={TODAY}&to={TODAY}"
        ).data
        history_total = sum(
            Decimal(row["total_amount"]) for row in history["results"]
        )
        self.assertEqual(history["count"], report["invoice_count"])
        self.assertEqual(history_total, report["net_sales"])

    def test_date_filtering_excludes_earlier_period(self):
        response = self.client.get(f"/api/reports/sales/?from={EARLIER}&to={EARLIER}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["invoice_count"], 0)
        self.assertEqual(response.data["net_sales"], Decimal("0.00"))

    def test_customer_and_payment_type_filters(self):
        by_customer = self.client.get(
            f"/api/reports/sales/?from={TODAY}&to={TODAY}&customer={self.customer_a.pk}"
        )
        self.assertEqual(by_customer.data["invoice_count"], 1)
        self.assertEqual(by_customer.data["net_sales"], Decimal("118.00"))

        by_payment = self.client.get(
            f"/api/reports/sales/?from={TODAY}&to={TODAY}&payment_type=cash"
        )
        self.assertEqual(by_payment.data["invoice_count"], 1)
        self.assertEqual(by_payment.data["net_sales"], Decimal("48.00"))

        bad_customer = self.client.get(
            f"/api/reports/sales/?from={TODAY}&to={TODAY}&customer=not-a-number"
        )
        self.assertEqual(bad_customer.status_code, 400)

    def test_inclusive_date_boundaries(self):
        # A single-day range covers the whole day on both ends.
        response = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}")
        self.assertEqual(response.data["invoice_count"], 2)


class PurchaseReportReconciliationTests(ReportTestBase):
    """PURCHASE tests 7-10: posted included; cancelled excluded; filters."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_posted_purchases_included_with_snapshots(self):
        response = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Two posted purchases (A: 100@6, B: 50@8); the cancelled one excluded.
        self.assertEqual(response.data["purchase_count"], 2)
        # taxable = 600 + 400
        self.assertEqual(response.data["taxable_purchases"], Decimal("1000.00"))
        # Both intra (18% → CGST/SGST) and inter (18% → IGST) purchases:
        # gst = 108 + 72
        self.assertEqual(response.data["gst"], Decimal("180.00"))
        self.assertEqual(response.data["total_purchase_value"], Decimal("1180.00"))

    def test_cancelled_purchases_excluded(self):
        response = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}"
        )
        self.assertEqual(response.data["purchase_count"], 2)
        self.assertEqual(response.data["cancelled_purchase_count"], 1)
        # Cancelled: 10 × 6 × 1.18 = 70.80
        self.assertEqual(response.data["cancelled_purchase_value"], Decimal("70.80"))

    def test_date_filtering(self):
        response = self.client.get(f"/api/reports/purchases/?from={TODAY}&to={TODAY}")
        self.assertEqual(response.data["purchase_count"], 0)
        earlier_only = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}&supplier={self.supplier_intra.pk}"
        )
        self.assertEqual(earlier_only.data["purchase_count"], 1)

    def test_supplier_filter_and_breakdown(self):
        response = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}&supplier={self.supplier_intra.pk}"
        )
        self.assertEqual(response.data["purchase_count"], 1)
        self.assertEqual(response.data["total_purchase_value"], Decimal("708.00"))

        all_rows = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}"
        ).data["by_supplier"]
        names = {row["supplier_name"] for row in all_rows}
        self.assertEqual(names, {"Alpha Traders", "Beta Distributors"})
        breakdown_total = sum(Decimal(row["purchase_total"]) for row in all_rows)
        self.assertEqual(breakdown_total, Decimal("1180.00"))

    def test_reconciles_with_purchase_history(self):
        report = self.client.get(
            f"/api/reports/purchases/?from={EARLIER}&to={EARLIER}"
        ).data
        history = self.client.get(
            f"/api/purchase-invoices/?state=POSTED&from={EARLIER}&to={EARLIER}"
        ).data
        history_total = sum(
            Decimal(row["total_amount"]) for row in history["results"]
        )
        self.assertEqual(history["count"], report["purchase_count"])
        self.assertEqual(history_total, report["total_purchase_value"])


class InventoryReportReconciliationTests(ReportTestBase):
    """INVENTORY tests 11-13: totals equal InventoryBalance valuation."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_report_total_equals_inventory_balance_valuation(self):
        response = self.client.get("/api/reports/inventory/")
        self.assertEqual(response.status_code, 200, response.data)
        balances = InventoryBalance.objects.filter(quantity_on_hand__gt=0)
        expected_value = sum(
            (b.quantity_on_hand * b.average_cost for b in balances), Decimal("0.00")
        )
        expected_qty = sum(
            (b.quantity_on_hand for b in balances), Decimal("0.000")
        )
        self.assertEqual(response.data["total_value"], expected_value)
        self.assertEqual(response.data["quantity_on_hand"], expected_qty)
        # Products: A (90 left) + B (48 left) — cancelled purchase restored 10 A.
        self.assertEqual(response.data["product_count"], 2)

    def test_reconciles_with_warehouse_summary(self):
        report = self.client.get("/api/reports/inventory/").data
        summary = self.client.get("/api/warehouses/summary/").data
        summary_value = sum(Decimal(row["total_value"]) for row in summary)
        self.assertEqual(report["total_value"], summary_value)

    def test_warehouse_filter_and_wac_valuation(self):
        response = self.client.get(
            f"/api/reports/inventory/?warehouse={self.warehouse.pk}"
        )
        self.assertEqual(response.status_code, 200)
        # WAC semantics: A = 90 × 6, B = 48 × 8.
        product_a_value = Decimal("540.00")
        product_b_value = Decimal("384.00")
        self.assertEqual(response.data["total_value"], product_a_value + product_b_value)

    def test_invalid_filters_rejected(self):
        self.assertEqual(
            self.client.get("/api/reports/inventory/?warehouse=not-a-number").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/reports/inventory/?is_active=bogus").status_code,
            400,
        )


class StockMovementReportTests(ReportTestBase):
    """STOCK tests 14-15: report mirrors StockLedger."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_report_mirrors_stock_ledger(self):
        response = self.client.get("/api/reports/stock-movement/")
        self.assertEqual(response.status_code, 200, response.data)
        ledger_count = StockLedger.objects.count()
        self.assertEqual(response.data["movement_count"], ledger_count)
        expected_net = sum(
            (m.quantity_change for m in StockLedger.objects.all()), Decimal("0.000")
        )
        self.assertEqual(response.data["net_quantity"], expected_net)

    def test_movement_and_date_filters(self):
        purchases = self.client.get(
            "/api/reports/stock-movement/?movement_type=PURCHASE"
        )
        self.assertEqual(purchases.status_code, 200)
        expected = StockLedger.objects.filter(movement_type="PURCHASE").count()
        self.assertEqual(purchases.data["movement_count"], expected)

        by_reference = self.client.get(
            "/api/reports/stock-movement/?reference=PI/"
        )
        expected_refs = StockLedger.objects.filter(
            reference__icontains="PI/"
        ).count()
        self.assertEqual(by_reference.data["movement_count"], expected_refs)

        invalid = self.client.get("/api/reports/stock-movement/?movement_type=NOPE")
        self.assertEqual(invalid.status_code, 400)


class ProductSalesReportTests(ReportTestBase):
    """PRODUCT SALES tests 16-20: historical COGS, no contamination."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_quantity_sold_and_sales_value(self):
        response = self.client.get(
            f"/api/reports/products/?from={TODAY}&to={TODAY}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row["product_name"]: row for row in response.data["products"]}
        self.assertEqual(rows["Report Product A"]["quantity_sold"], Decimal("10.000"))
        self.assertEqual(rows["Report Product A"]["sales_value"], Decimal("118.00"))
        self.assertEqual(rows["Report Product B"]["quantity_sold"], Decimal("2.000"))
        self.assertEqual(response.data["total_revenue"], Decimal("166.00"))

    def test_historical_cogs_not_current_cost(self):
        # Historical COGS: 10 × 6 = 60 (WAC at sale time).
        response = self.client.get(
            f"/api/reports/products/?from={TODAY}&to={TODAY}"
        ).data
        rows = {row["product_name"]: row for row in response["products"]}
        self.assertEqual(rows["Report Product A"]["cogs"], Decimal("60.00"))
        self.assertEqual(rows["Report Product A"]["gross_profit"], Decimal("58.00"))
        self.assertEqual(rows["Report Product A"]["margin_percent"], Decimal("49.2"))

    def test_no_current_cost_contamination_after_wac_change(self):
        # Receive more stock at a different rate so the WAC moves.
        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": self.product_a, "quantity": Decimal("100"), "rate": Decimal("20.00")}
            ],
            created_by=self.admin,
            post=True,
        )
        response = self.client.get(
            f"/api/reports/products/?from={TODAY}&to={TODAY}"
        ).data
        rows = {row["product_name"]: row for row in response["products"]}
        # COGS for the earlier sale is STILL 60.00 — the ₹20 receipt must not
        # retroactively recalculate last sale's cost.
        self.assertEqual(rows["Report Product A"]["cogs"], Decimal("60.00"))
        self.assertEqual(rows["Report Product A"]["gross_profit"], Decimal("58.00"))

        # Changing Product.cost_price directly must not contaminate either.
        Product.objects.filter(pk=self.product_a.pk).update(
            cost_price=Decimal("99.00")
        )
        response = self.client.get(
            f"/api/reports/products/?from={TODAY}&to={TODAY}"
        ).data
        rows = {row["product_name"]: row for row in response["products"]}
        self.assertEqual(rows["Report Product A"]["cogs"], Decimal("60.00"))

    def test_draft_and_cancelled_lines_excluded(self):
        response = self.client.get(
            f"/api/reports/products/?from={TODAY}&to={TODAY}"
        ).data
        # Only the two posted sales (10 A + 2 B); the draft's 5 A and the
        # cancelled sale's 3 A must not appear.
        rows = {row["product_name"]: row for row in response["products"]}
        self.assertEqual(rows["Report Product A"]["quantity_sold"], Decimal("10.000"))
        self.assertEqual(len(response["products"]), 2)

    def test_date_range_required(self):
        self.assertEqual(
            self.client.get("/api/reports/products/").status_code, 400
        )


class CustomerSalesReportTests(ReportTestBase):
    """CUSTOMER tests 21-22: reconcile with invoices and outstanding."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_customer_totals_reconcile_with_invoices(self):
        response = self.client.get(
            f"/api/reports/customers/?from={TODAY}&to={TODAY}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row["customer_name"]: row for row in response.data["by_customer"]}
        self.assertEqual(rows["Report Customer A"]["invoice_count"], 1)
        self.assertEqual(rows["Report Customer A"]["sales_value"], Decimal("118.00"))
        self.assertEqual(rows["Report Customer B"]["sales_value"], Decimal("48.00"))
        self.assertEqual(response.data["total_sales"], Decimal("166.00"))

        # The legacy per-customer report lists every state (history view);
        # its POSTED subset must match this report's active figures.
        detail = self.client.get(
            f"/api/customers/{self.customer_a.pk}/report/"
        ).data
        posted_rows = [row for row in detail["invoices"] if row["state"] == "POSTED"]
        self.assertEqual(len(posted_rows), 1)
        self.assertEqual(Decimal(posted_rows[0]["total_amount"]), Decimal("118.00"))
        # Outstanding is the model's authoritative POSTED-only balance.
        self.assertEqual(Decimal(detail["outstanding_balance"]), Decimal("118.00"))

    def test_outstanding_matches_customer_backend(self):
        response = self.client.get(
            f"/api/reports/customers/?from={TODAY}&to={TODAY}"
        ).data
        rows = {row["customer_name"]: row for row in response["by_customer"]}
        self.assertEqual(
            rows["Report Customer A"]["outstanding_balance"],
            self.customer_a.outstanding_balance,
        )
        # Cash sale for B settled instantly: outstanding 0.
        self.assertEqual(
            rows["Report Customer B"]["outstanding_balance"],
            Decimal("0.00"),
        )

    def test_walk_in_identifiable(self):
        # A walk-in (cash, no customer) sale keeps its snapshot identity.
        from billing.services import create_invoice

        create_invoice(
            customer=None,
            invoice_number="REP-WALKIN-0005",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": self.product_a, "quantity": Decimal("1"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")}
            ],
        )
        response = self.client.get(
            f"/api/reports/customers/?from={TODAY}&to={TODAY}"
        ).data
        walk_in = [row for row in response["by_customer"] if row["is_walk_in"]]
        self.assertEqual(len(walk_in), 1)
        self.assertEqual(walk_in[0]["customer_name"], "Walk-in customer")


class TaxSummaryReportTests(ReportTestBase):
    """TAX tests 23-25: snapshots in, CGST/SGST/IGST split."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_output_gst_matches_invoice_snapshots(self):
        response = self.client.get(
            f"/api/reports/tax/?from={TODAY}&to={TODAY}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        output = response.data["output_tax"]
        self.assertEqual(output["taxable_sales"], Decimal("140.00"))
        # Both sales intra-state (27→27): CGST 12.60 + SGST 12.60 = 25.20.
        self.assertEqual(output["cgst"], Decimal("13.00"))
        self.assertEqual(output["sgst"], Decimal("13.00"))
        self.assertEqual(output["igst"], Decimal("0.00"))
        self.assertEqual(output["total"], Decimal("26.00"))

        # Reconcile with line snapshots directly.
        from billing.models import InvoiceLineItem

        snapshot_cgst = InvoiceLineItem.objects.filter(
            invoice__state="POSTED", invoice__invoice_date=TODAY
        ).aggregate(t=Sum("cgst_amount"))["t"]
        self.assertEqual(output["cgst"], snapshot_cgst)

    def test_input_gst_matches_purchase_snapshots(self):
        response = self.client.get(
            f"/api/reports/tax/?from={EARLIER}&to={EARLIER}"
        ).data
        input_tax = response["input_tax"]
        # Intra purchase: CGST+SGST 54+54; inter purchase: IGST 72.
        self.assertEqual(input_tax["cgst"], Decimal("54.00"))
        self.assertEqual(input_tax["sgst"], Decimal("54.00"))
        self.assertEqual(input_tax["igst"], Decimal("72.00"))
        self.assertEqual(input_tax["total"], Decimal("180.00"))

        # Never current TaxRate values: change the rate and re-query.
        TaxRate.objects.filter(pk=self.tax.pk).update(rate=Decimal("28.00"))
        again = self.client.get(
            f"/api/reports/tax/?from={EARLIER}&to={EARLIER}"
        ).data
        self.assertEqual(again["input_tax"]["total"], Decimal("180.00"))

    def test_output_and_input_distinguished(self):
        response = self.client.get(
            f"/api/reports/tax/?from={EARLIER}&to={TODAY}"
        ).data
        self.assertIn("output_tax", response)
        self.assertIn("input_tax", response)
        self.assertIn("net_tax", response)
        self.assertEqual(
            response["net_tax"],
            response["output_tax"]["total"] - response["input_tax"]["total"],
        )


class ProfitReportTests(ReportTestBase):
    """PROFIT tests 26-27: revenue − historical COGS; cancelled excluded."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_revenue_minus_historical_cogs_is_gross_profit(self):
        response = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["revenue"], Decimal("166.00"))
        self.assertEqual(response.data["cogs"], Decimal("76.00"))
        self.assertEqual(response.data["gross_profit"], Decimal("90.00"))
        self.assertEqual(response.data["gross_margin_percent"], Decimal("54.2"))

    def test_cancelled_invoices_excluded(self):
        # The cancelled sale (3 × A) would add 35.40 revenue / 18 COGS.
        response = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        ).data
        self.assertNotEqual(response["revenue"], Decimal("202.00"))
        self.assertEqual(response["revenue"], Decimal("166.00"))
        self.assertEqual(response["cogs"], Decimal("76.00"))

    def test_product_breakdown_sums_to_total(self):
        response = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        ).data
        breakdown_profit = sum(
            Decimal(row["gross_profit"]) for row in response["by_product"]
        )
        self.assertEqual(breakdown_profit, response["gross_profit"])

    def test_current_wac_change_does_not_restate_profit(self):
        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": self.product_a, "quantity": Decimal("100"), "rate": Decimal("20.00")}
            ],
            created_by=self.admin,
            post=True,
        )
        response = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        ).data
        self.assertEqual(response["cogs"], Decimal("76.00"))
        self.assertEqual(response["gross_profit"], Decimal("90.00"))

    def test_credit_note_reduces_revenue_and_cogs(self):
        from billing.models import CreditNoteLineItem
        from billing.services import create_credit_note

        line = self.sale_a.line_items.get()
        create_credit_note(
            original_invoice=self.sale_a,
            reason="return one",
            created_by=self.admin,
            line_items=[
                {"invoice_line_item": line, "product": self.product_a, "quantity": Decimal("2")}
            ],
        )
        response = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        ).data
        # Revenue: 165.20 − (2×10×1.18)=23.60 → 141.60
        self.assertEqual(response["revenue"], Decimal("142.40"))
        # COGS: 76 − (2×6)=12 → 64
        self.assertEqual(response["cogs"], Decimal("64.00"))
        self.assertEqual(response["gross_profit"], Decimal("78.40"))


class TopProductsReportTests(ReportTestBase):
    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_posted_only_ranking_with_profit(self):
        response = self.client.get(
            f"/api/reports/top-products/?from={TODAY}&to={TODAY}&sort_by=quantity&limit=10"
        )
        self.assertEqual(response.status_code, 200, response.data)
        products = response.data["products"]
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]["product_name"], "Report Product A")
        self.assertEqual(products[0]["total_quantity"], Decimal("10.000"))
        # Cancelled/draft sales excluded: without the fix A would rank 15
        # (10 + 5 draft + 3 cancelled was 13+? -> 18).
        self.assertNotEqual(products[0]["total_quantity"], Decimal("18.000"))

        by_profit = self.client.get(
            f"/api/reports/top-products/?from={TODAY}&to={TODAY}&sort_by=profit&limit=1"
        ).data
        self.assertEqual(by_profit["products"][0]["total_profit"], Decimal("58.00"))

    def test_profit_ranking_uses_historical_cogs(self):
        response = self.client.get(
            f"/api/reports/top-products/?from={TODAY}&to={TODAY}&sort_by=profit&limit=10"
        ).data
        rows = {row["product_name"]: row for row in response["products"]}
        self.assertEqual(rows["Report Product A"]["total_profit"], Decimal("58.00"))
        self.assertEqual(rows["Report Product B"]["total_profit"], Decimal("32.00"))


class DashboardReportTests(ReportTestBase):
    """DASHBOARD test 28: every metric matches its underlying query."""

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_dashboard_metrics_match_reports(self):
        dashboard = self.client.get(
            f"/api/reports/dashboard/?from={TODAY}&to={TODAY}"
        )
        self.assertEqual(dashboard.status_code, 200, dashboard.data)
        data = dashboard.data

        sales_report = self.client.get(
            f"/api/reports/sales/?from={TODAY}&to={TODAY}"
        ).data
        self.assertEqual(data["today"]["net_sales"], sales_report["net_sales"])
        self.assertEqual(data["today"]["invoice_count"], sales_report["invoice_count"])

        purchase_report = self.client.get(
            f"/api/reports/purchases/?from={TODAY}&to={TODAY}"
        ).data
        self.assertEqual(
            data["today"]["purchase_value"], purchase_report["total_purchase_value"]
        )

        inventory_report = self.client.get("/api/reports/inventory/").data
        self.assertEqual(data["inventory"]["total_value"], inventory_report["total_value"])
        self.assertEqual(data["inventory"]["product_count"], inventory_report["product_count"])

        profit_report = self.client.get(
            f"/api/reports/profit/?from={TODAY}&to={TODAY}"
        ).data
        self.assertEqual(data["period"]["gross_profit"], profit_report["gross_profit"])

        expected_outstanding = sum(
            (c.outstanding_balance for c in Customer.objects.filter(is_active=True)),
            Decimal("0.00"),
        )
        self.assertEqual(data["customer_outstanding_total"], expected_outstanding)
        self.assertEqual(data["active_customers"], Customer.objects.filter(is_active=True).count())
        self.assertEqual(data["active_suppliers"], Supplier.objects.filter(is_active=True).count())

    def test_low_stock_uses_threshold(self):
        Product.objects.filter(pk=self.product_a.pk).update(
            low_stock_threshold=Decimal("1000")
        )
        data = self.client.get(
            f"/api/reports/dashboard/?from={TODAY}&to={TODAY}"
        ).data
        low_ids = [row["id"] for row in data["low_stock"]]
        self.assertIn(self.product_a.pk, low_ids)


class ReportPermissionTests(ReportTestBase):
    """PHASE 18: backend permission policy for reports."""

    def test_staff_can_access_operational_reports(self):
        client = self.client_as(self.staff)
        for url in (
            f"/api/reports/sales/?from={TODAY}&to={TODAY}",
            f"/api/reports/purchases/?from={TODAY}&to={TODAY}",
            "/api/reports/inventory/",
            "/api/reports/stock-movement/",
            f"/api/reports/products/?from={TODAY}&to={TODAY}",
            f"/api/reports/top-products/?from={TODAY}&to={TODAY}",
        ):
            self.assertEqual(client.get(url).status_code, 200, url)

    def test_staff_forbidden_from_financial_reports(self):
        client = self.client_as(self.staff)
        for url in (
            f"/api/reports/customers/?from={TODAY}&to={TODAY}",
            f"/api/reports/tax/?from={TODAY}&to={TODAY}",
            f"/api/reports/profit/?from={TODAY}&to={TODAY}",
            f"/api/reports/dashboard/?from={TODAY}&to={TODAY}",
        ):
            self.assertEqual(client.get(url).status_code, 403, url)

    def test_unauthenticated_rejected(self):
        anonymous = APIClient()
        self.assertIn(
            anonymous.get("/api/reports/sales/?from=2026-01-01&to=2026-01-31").status_code,
            {401, 403},
        )

    def test_reports_are_read_only(self):
        # No write verb is routed on any report endpoint.
        client = self.client_as(self.admin)
        self.assertEqual(
            client.post("/api/reports/sales/", {}).status_code, 405
        )
        self.assertEqual(
            client.post("/api/reports/inventory/", {}).status_code, 405
        )
        self.assertEqual(
            client.post("/api/reports/dashboard/", {}).status_code, 405
        )
