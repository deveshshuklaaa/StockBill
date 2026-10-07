"""Comprehensive Gross Profit Accounting Regression and Edge-Case Tests.

Verifies:
1. Exact bug scenario: Yellow Banana Chips (Purchase 100 @ 6.66 + 5% GST; Sale 100 @ 7.35 + 5% GST).
   - Tax-exclusive Sales Revenue = 735.00
   - Tax-exclusive COGS = 666.00
   - Gross Profit = 69.00
   - Proves no mixing of tax-inclusive sales (771.75) and tax-exclusive COGS (666.00).
2. Edge cases:
   - Same GST rate on purchase and sale
   - Different purchase and sale GST rates
   - GST-exempt purchase/sale (0%)
   - IGST (inter-state)
   - CGST + SGST (intra-state)
   - Multiple purchase lots with different costs
   - WAC across multiple purchases
   - Partial sale from stock
   - Multiple invoice lines
   - Cancelled invoices excluded from Gross Profit
   - Draft invoices excluded from Gross Profit
   - Historical COGS snapshot remains unchanged after later purchases
   - Rounding at paise boundaries
   - Customer-specific selling price / custom pricing
   - Purchase discount affecting actual purchase cost
   - Consistency across Profit Report, Dashboard, Product Sales, and Sales Summary
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from billing.reports import get_profit_report_data
from billing.services import cancel_invoice, create_invoice
from customers.models import Customer
from inventory.models import (
    InventoryBalance,
    Product,
    PurchaseInvoice,
    Supplier,
    TaxRate,
    Warehouse,
)
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse

User = get_user_model()
TODAY = timezone.localdate()
YESTERDAY = TODAY - datetime.timedelta(days=1)


class GrossProfitAccountingTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="gp-admin", password="AdminPassword123!", role="admin"
        )
        cls.business = BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            gstin="27DIVYA1234A1Z5",
            registered_address="123 Market Road, Mumbai",
            state="Maharashtra",
            state_code="27",
        )
        cls.warehouse = get_default_warehouse()

        cls.tax_0, _ = TaxRate.objects.get_or_create(
            name="GST 0%", defaults={"rate": Decimal("0.00")}
        )
        cls.tax_5, _ = TaxRate.objects.get_or_create(
            name="GST 5%", defaults={"rate": Decimal("5.00")}
        )
        cls.tax_12, _ = TaxRate.objects.get_or_create(
            name="GST 12%", defaults={"rate": Decimal("12.00")}
        )
        cls.tax_18, _ = TaxRate.objects.get_or_create(
            name="GST 18%", defaults={"rate": Decimal("18.00")}
        )

        cls.supplier_intra = Supplier.objects.create(
            name="Local Supplier MH",
            gstin="27AAACS1111A1Z1",
            state="Maharashtra",
            state_code="27",
        )
        cls.supplier_inter = Supplier.objects.create(
            name="Interstate Supplier GJ",
            gstin="24AAACS2222B1Z2",
            state="Gujarat",
            state_code="24",
        )

        cls.customer_intra = Customer.objects.create(
            name="Local Retailer MH",
            gstin="27AAACC3333C1Z3",
            state="Maharashtra",
            state_code="27",
            credit_limit=Decimal("500000.00"),
        )
        cls.customer_inter = Customer.objects.create(
            name="Interstate Retailer KA",
            gstin="29AAACC4444D1Z4",
            state="Karnataka",
            state_code="29",
            credit_limit=Decimal("500000.00"),
        )

    def setUp(self):
        self.client.force_authenticate(user=self.admin)

    def _create_product(self, name, default_price, tax_rate_obj, mrp=None):
        return Product.objects.create(
            name=name,
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=Decimal(str(default_price)),
            mrp=Decimal(str(mrp)) if mrp else Decimal(str(default_price)),
            cost_price=Decimal("0.00"),
            tax=tax_rate_obj,
            current_stock=0,
        )

    def test_01_exact_bug_scenario(self):
        """Purchase 100 Banana Chips @ 6.66 + 5% GST; Sale 100 @ 7.35 + 5% GST.

        Checks:
        - Purchase Taxable: 666.00, GST: 33.30, Total: 699.30
        - Sale Taxable: 735.00, GST: 36.75, Total: 771.75
        - COGS: 666.00 (tax-exclusive WAC)
        - Gross Profit: 69.00 (735.00 - 666.00)
        - PROVES system does NOT do 771.75 - 666.00 = 105.75
        """
        product = self._create_product("Yellow Banana Chips", "7.35", self.tax_5, mrp="10.00")

        # Purchase: 100 pcs @ 6.66 per piece (tax-exclusive)
        purch = create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {
                    "product": product,
                    "quantity": Decimal("100"),
                    "rate": Decimal("6.66"),
                    "tax_rate": Decimal("5.00"),
                }
            ],
            created_by=self.admin,
            post=True,
        )

        self.assertEqual(purch.taxable_total, Decimal("666.00"))
        self.assertEqual(purch.cgst_total + purch.sgst_total + purch.igst_total, Decimal("33.30"))
        self.assertEqual(purch.total_amount, Decimal("699.30"))

        # Verify WAC is pre-tax 6.66
        bal = InventoryBalance.objects.get(product=product, warehouse=self.warehouse)
        self.assertEqual(bal.average_cost, Decimal("6.66"))

        # Sale: 100 pcs @ 7.35 per piece (tax-exclusive rate)
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-BUG-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {
                    "product": product,
                    "quantity": Decimal("100"),
                    "rate_charged": Decimal("7.35"),
                    "tax_rate": Decimal("5.00"),
                }
            ],
        )

        line = inv.line_items.first()
        self.assertEqual(line.taxable_value_snapshot, Decimal("735.00"))
        self.assertEqual(line.tax_amount, Decimal("36.75"))
        self.assertEqual(line.line_total, Decimal("771.75"))
        self.assertEqual(line.cogs_amount, Decimal("666.00"))
        self.assertEqual(line.cost_price_snapshot, Decimal("6.66"))

        # Authoritative Profit Report check
        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("735.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("666.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("69.00"))
        self.assertEqual(profit_data["sales_gst"], Decimal("36.75"))
        self.assertEqual(profit_data["total_sales_value"], Decimal("771.75"))
        # Margin % = 69.00 / 735.00 * 100 = 9.3877... -> 9.39%
        self.assertEqual(profit_data["gross_margin_percent"], Decimal("9.4"))

        # Explicit assertion that profit != 771.75 - 666.00 (105.75)
        self.assertNotEqual(profit_data["gross_profit"], Decimal("105.75"))

        # Test API response
        resp = self.client.get(f"/api/reports/profit/?from={TODAY}&to={TODAY}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["gross_profit"], Decimal("69.00"))
        self.assertEqual(resp.data["taxable_sales_revenue"], Decimal("735.00"))
        self.assertEqual(resp.data["taxable_cogs"], Decimal("666.00"))

    def test_02_different_purchase_and_sale_gst_rates(self):
        """Purchase at 5% GST, reclassified to 18% GST before sale.

        Tax-exclusive profit must remain independent of output vs input tax rates.
        """
        product = self._create_product("Rate Shift Item", "100.00", self.tax_5)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate": Decimal("50.00"), "tax_rate": Decimal("5.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # Reclassify product tax rate
        product.tax = self.tax_18
        product.save()

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-DIFF-RATE-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("100.00"), "tax_rate": Decimal("18.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        # Taxable Revenue: 1000.00, Taxable COGS: 500.00 -> Profit: 500.00
        # Output GST: 180.00. If tax-inclusive was mixed, profit would have been 1180 - 500 = 680 (WRONG).
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1000.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("500.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("500.00"))
        self.assertEqual(profit_data["sales_gst"], Decimal("180.00"))

    def test_03_gst_exempt_purchase_and_sale(self):
        """0% GST items (exempt goods like fresh grain/produce)."""
        product = self._create_product("Exempt Item", "50.00", self.tax_0)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("20"), "rate": Decimal("30.00"), "tax_rate": Decimal("0.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-EXEMPT-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("20"), "rate_charged": Decimal("50.00"), "tax_rate": Decimal("0.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        # Revenue: 1000.00, COGS: 600.00 -> Profit: 400.00
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1000.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("600.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("400.00"))
        self.assertEqual(profit_data["sales_gst"], Decimal("0.00"))

    def test_04_igst_interstate_transactions(self):
        """Inter-state purchase (IGST) and inter-state sale (IGST)."""
        product = self._create_product("Interstate Item", "200.00", self.tax_18)

        # Purchase from Gujarat to Maharashtra -> IGST 18%
        purch = create_purchase(
            supplier=self.supplier_inter,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate": Decimal("120.00"), "tax_rate": Decimal("18.00")}
            ],
            created_by=self.admin,
            post=True,
        )
        self.assertEqual(purch.igst_total, Decimal("216.00"))

        # Sale from Maharashtra to Karnataka -> IGST 18%
        inv = create_invoice(
            customer=self.customer_inter,
            invoice_number="INV-IGST-001",
            created_by=self.admin,
            payment_type="credit",
            line_items=[
                {"product": product, "quantity": Decimal("5"), "rate_charged": Decimal("200.00"), "tax_rate": Decimal("18.00")}
            ],
        )
        line = inv.line_items.first()
        self.assertEqual(line.igst_amount, Decimal("180.00"))
        self.assertEqual(line.cgst_amount, Decimal("0.00"))
        self.assertEqual(line.sgst_amount, Decimal("0.00"))

        profit_data = get_profit_report_data(TODAY, TODAY)
        # Revenue: 5 * 200 = 1000.00, COGS: 5 * 120 = 600.00 -> Profit: 400.00
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1000.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("600.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("400.00"))

    def test_05_cgst_sgst_intrastate_split(self):
        """Intra-state transactions verifying CGST and SGST splits do not affect gross profit."""
        product = self._create_product("Intrastate Item", "100.00", self.tax_18)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate": Decimal("60.00"), "tax_rate": Decimal("18.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-INTRA-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("100.00"), "tax_rate": Decimal("18.00")}
            ],
        )
        line = inv.line_items.first()
        self.assertEqual(line.cgst_amount, Decimal("90.00"))
        self.assertEqual(line.sgst_amount, Decimal("90.00"))
        self.assertEqual(line.igst_amount, Decimal("0.00"))

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1000.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("600.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("400.00"))

    def test_06_multiple_purchase_lots_and_wac_blending(self):
        """Lot 1: 100 @ 10 = 1000; Lot 2: 100 @ 20 = 2000.

        WAC = 3000 / 200 = 15.00.
        Sale: 50 @ 25 = 1250.
        COGS = 50 * 15 = 750.
        Profit = 1250 - 750 = 500.
        """
        product = self._create_product("WAC Test Product", "25.00", self.tax_12)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("10.00"), "tax_rate": Decimal("12.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("20.00"), "tax_rate": Decimal("12.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        bal = InventoryBalance.objects.get(product=product, warehouse=self.warehouse)
        self.assertEqual(bal.average_cost, Decimal("15.00"))

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-WAC-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("50"), "rate_charged": Decimal("25.00"), "tax_rate": Decimal("12.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1250.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("750.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("500.00"))

    def test_07_partial_sale_from_stock(self):
        """Buy 100, sell 30, leaving 70 in stock."""
        product = self._create_product("Partial Item", "50.00", self.tax_5)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("30.00"), "tax_rate": Decimal("5.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-PARTIAL-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("30"), "rate_charged": Decimal("50.00"), "tax_rate": Decimal("5.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1500.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("900.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("600.00"))

    def test_08_multiple_invoice_lines(self):
        """Single invoice containing multiple lines with different products and tax rates."""
        p1 = self._create_product("Multi Line A", "10.00", self.tax_5)
        p2 = self._create_product("Multi Line B", "20.00", self.tax_18)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": p1, "quantity": Decimal("100"), "rate": Decimal("6.00"), "tax_rate": Decimal("5.00")},
                {"product": p2, "quantity": Decimal("100"), "rate": Decimal("12.00"), "tax_rate": Decimal("18.00")},
            ],
            created_by=self.admin,
            post=True,
        )

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-MULTI-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": p1, "quantity": Decimal("10"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("5.00")},
                {"product": p2, "quantity": Decimal("5"), "rate_charged": Decimal("20.00"), "tax_rate": Decimal("18.00")},
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("200.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("120.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("80.00"))

    def test_09_cancelled_and_draft_invoices_excluded(self):
        """Draft and Cancelled invoices must be strictly excluded from gross profit."""
        product = self._create_product("State Exclusion Item", "100.00", self.tax_18)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("50.00"), "tax_rate": Decimal("18.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # 1. Posted invoice: 10 @ 100 -> rev 1000, cogs 500, profit 500
        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-STATE-POSTED",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("100.00"), "tax_rate": Decimal("18.00")}
            ],
        )

        # 2. Draft invoice: 10 @ 100 -> MUST NOT affect profit
        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-STATE-DRAFT",
            created_by=self.admin,
            payment_type="credit",
            state=Invoice.STATE_DRAFT,
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("100.00"), "tax_rate": Decimal("18.00")}
            ],
        )

        # 3. Cancelled invoice: 10 @ 100 -> MUST NOT affect profit
        cancelled_inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-STATE-CANCELLED",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("100.00"), "tax_rate": Decimal("18.00")}
            ],
        )
        cancel_invoice(invoice_id=cancelled_inv.id, cancelled_by=self.admin, reason="Test cancellation")

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("1000.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("500.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("500.00"))

    def test_10_historical_cogs_snapshot_immutability(self):
        """Later purchases at higher or lower cost do NOT alter historical sale COGS or profit."""
        product = self._create_product("Historical Item", "20.00", self.tax_5)

        # Buy 50 @ 10.00
        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("50"), "rate": Decimal("10.00"), "tax_rate": Decimal("5.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # Sell 10 @ 20.00 -> COGS = 10 * 10 = 100, Revenue = 200, Profit = 100
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-HIST-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("20.00"), "tax_rate": Decimal("5.00")}
            ],
        )

        # Subsequent purchase at 18.00 alters WAC
        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("18.00"), "tax_rate": Decimal("5.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # Re-check invoice line: snapshot must still be 10.00 cost, 100.00 COGS
        inv.refresh_from_db()
        line = inv.line_items.first()
        self.assertEqual(line.cost_price_snapshot, Decimal("10.00"))
        self.assertEqual(line.cogs_amount, Decimal("100.00"))

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("200.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("100.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("100.00"))

    def test_11_rounding_at_paise_boundaries(self):
        """Rates with fractional paise amounts properly rounded without floating point error."""
        product = self._create_product("Paise Rounding Item", "3.33", self.tax_5)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("3"), "rate": Decimal("2.11"), "tax_rate": Decimal("5.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # 3 * 3.33 = 9.99 revenue. COGS: 3 * 2.11 = 6.33. Profit = 3.66.
        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-PAISE-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("3"), "rate_charged": Decimal("3.33"), "tax_rate": Decimal("5.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("9.99"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("6.33"))
        self.assertEqual(profit_data["gross_profit"], Decimal("3.66"))

    def test_12_purchase_discount_affects_cost(self):
        """Purchase discount reduces the taxable unit cost and therefore COGS."""
        product = self._create_product("Discounted Item", "20.00", self.tax_18)

        # Buy 100 @ 10.00 = 1000.00 gross, discount 100.00 -> net taxable = 900.00
        # WAC = 900.00 / 100 = 9.00
        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {
                    "product": product,
                    "quantity": Decimal("100"),
                    "rate": Decimal("10.00"),
                    "discount_amount": Decimal("100.00"),
                    "tax_rate": Decimal("18.00"),
                }
            ],
            created_by=self.admin,
            post=True,
        )

        bal = InventoryBalance.objects.get(product=product, warehouse=self.warehouse)
        self.assertEqual(bal.average_cost, Decimal("9.00"))

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-DISC-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("20.00"), "tax_rate": Decimal("18.00")}
            ],
        )

        profit_data = get_profit_report_data(TODAY, TODAY)
        # Revenue: 200.00, COGS: 90.00 -> Profit: 110.00
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("200.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("90.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("110.00"))

    def test_13_customer_specific_pricing_and_mrp(self):
        """Sale with negotiated customer rate different from MRP and default price."""
        product = self._create_product("MRP Product", "100.00", self.tax_18, mrp="120.00")

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("10"), "rate": Decimal("60.00"), "tax_rate": Decimal("18.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        # Charged rate is ₹90 (negotiated, below default 100 and MRP 120)
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-CUST-PRICE-001",
            created_by=self.admin,
            payment_type="credit",
            line_items=[
                {"product": product, "quantity": Decimal("5"), "rate_charged": Decimal("90.00"), "tax_rate": Decimal("18.00")}
            ],
        )
        line = inv.line_items.first()
        self.assertEqual(line.rate_charged, Decimal("90.00"))
        self.assertEqual(line.mrp_snapshot, Decimal("120.00"))
        self.assertEqual(line.taxable_value_snapshot, Decimal("450.00"))
        self.assertEqual(line.cogs_amount, Decimal("300.00"))

        profit_data = get_profit_report_data(TODAY, TODAY)
        self.assertEqual(profit_data["taxable_sales_revenue"], Decimal("450.00"))
        self.assertEqual(profit_data["taxable_cogs"], Decimal("300.00"))
        self.assertEqual(profit_data["gross_profit"], Decimal("150.00"))

    def test_14_report_consistency_across_views(self):
        """Profit Report, Dashboard, Product Sales Report, and Sales Summary all agree."""
        product = self._create_product("Consistency Product", "50.00", self.tax_18)

        create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=TODAY,
            line_items=[
                {"product": product, "quantity": Decimal("100"), "rate": Decimal("30.00"), "tax_rate": Decimal("18.00")}
            ],
            created_by=self.admin,
            post=True,
        )

        create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-CONSIST-001",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {"product": product, "quantity": Decimal("20"), "rate_charged": Decimal("50.00"), "tax_rate": Decimal("18.00")}
            ],
        )

        # Revenue: 1000.00, COGS: 600.00, Profit: 400.00
        # 1. Profit Report View
        res_profit = self.client.get(f"/api/reports/profit/?from={TODAY}&to={TODAY}")
        self.assertEqual(res_profit.status_code, 200)
        self.assertEqual(Decimal(str(res_profit.data["gross_profit"])), Decimal("400.00"))
        self.assertEqual(Decimal(str(res_profit.data["revenue"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(res_profit.data["cogs"])), Decimal("600.00"))

        # 2. Dashboard Report View
        res_dash = self.client.get(f"/api/reports/dashboard/?from={TODAY}&to={TODAY}")
        self.assertEqual(res_dash.status_code, 200)
        self.assertEqual(Decimal(str(res_dash.data["period"]["gross_profit"])), Decimal("400.00"))
        self.assertEqual(Decimal(str(res_dash.data["period"]["revenue"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(res_dash.data["period"]["cogs"])), Decimal("600.00"))

        # 3. Product Sales Report View
        res_prod = self.client.get(f"/api/reports/products/?from={TODAY}&to={TODAY}")
        self.assertEqual(res_prod.status_code, 200)
        self.assertEqual(Decimal(str(res_prod.data["total_gross_profit"])), Decimal("400.00"))
        self.assertEqual(Decimal(str(res_prod.data["total_revenue"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(res_prod.data["total_cogs"])), Decimal("600.00"))
        # Check individual row
        row = res_prod.data["products"][0]
        self.assertEqual(Decimal(str(row["taxable_sales_revenue"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(row["cogs"])), Decimal("600.00"))
        self.assertEqual(Decimal(str(row["gross_profit"])), Decimal("400.00"))

        # 4. Sales Summary View
        res_summary = self.client.get(f"/api/reports/sales/?from={TODAY}&to={TODAY}")
        self.assertEqual(res_summary.status_code, 200)
        self.assertEqual(Decimal(str(res_summary.data["gross_profit"])), Decimal("400.00"))
        self.assertEqual(Decimal(str(res_summary.data["taxable_sales"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(res_summary.data["cogs"])), Decimal("600.00"))
