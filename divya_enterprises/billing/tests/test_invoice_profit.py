"""Invoice-detail profitability uses the original posted cost/tax snapshots."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from billing.models import BusinessProfile, Invoice
from billing.services import cancel_invoice, create_credit_note, create_invoice
from customers.models import Customer
from inventory.models import AttributeDefinition, Product, ProductAttributeValue, StockLedger, Supplier, TaxRate
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse


class InvoiceProfitTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="invoice-profit-admin", role="admin")
        cls.staff = get_user_model().objects.create_user(username="invoice-profit-staff", role="staff")
        BusinessProfile.objects.create(business_name="Test business", state_code="27")
        cls.customer = Customer.objects.create(name="Test customer", state_code="27")
        cls.supplier = Supplier.objects.create(name="Test supplier", state_code="27")
        cls.tax, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})
        cls.warehouse = get_default_warehouse()

    def setUp(self):
        self.client.force_authenticate(self.staff)

    def product(self, name, cost, quantity="200"):
        product = Product.objects.create(name=name, base_unit="piece", tax=self.tax)
        create_purchase(
            supplier=self.supplier, warehouse=self.warehouse, invoice_date=timezone.localdate(),
            line_items=[{"product": product, "quantity": Decimal(quantity), "rate": Decimal(cost)}],
            created_by=self.admin, post=True,
        )
        return product

    def invoice(self, lines, **kwargs):
        return create_invoice(
            customer=self.customer, invoice_number=f"INV-PROFIT-{Invoice.objects.count() + 1}",
            created_by=self.admin, payment_type="credit", line_items=lines, **kwargs,
        )

    def detail(self, invoice):
        response = self.client.get(f"/api/invoices/{invoice.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["profit_summary"]

    def test_exclusive_invoice_and_product_percentage_use_historical_cost(self):
        product = self.product("Test snack", "6.66")
        invoice = self.invoice([{"product": product, "quantity": Decimal("108"), "rate_charged": Decimal("8.10")}])
        before = StockLedger.objects.count()
        summary = self.detail(invoice)
        self.assertEqual(summary["taxable_sales_revenue"], Decimal("874.80"))
        self.assertEqual(summary["taxable_cogs"], Decimal("719.28"))
        self.assertEqual(summary["gross_profit"], Decimal("155.52"))
        self.assertEqual(summary["margin_percent"], Decimal("21.6"))
        self.assertEqual(summary["products"][0]["margin_percent"], Decimal("21.6"))
        self.assertEqual(StockLedger.objects.count(), before)

    def test_inclusive_invoice_survives_later_wac_and_master_price_changes(self):
        product = self.product("Test gift pack", "175.66")
        invoice = self.invoice(
            [{"product": product, "quantity": Decimal("12"), "rate_charged": Decimal("199.20")}],
            tax_mode=Invoice.TAX_MODE_INCLUSIVE,
        )
        original = self.detail(invoice)
        self.assertEqual(original["taxable_sales_revenue"], Decimal("2276.57"))
        self.assertEqual(original["taxable_cogs"], Decimal("2107.92"))
        self.assertEqual(original["gross_profit"], Decimal("168.65"))
        self.assertEqual(original["margin_percent"], Decimal("8.0"))
        Product.objects.filter(pk=product.pk).update(name="Changed name", cost_price=999, default_price=999)
        create_purchase(
            supplier=self.supplier, warehouse=self.warehouse, invoice_date=timezone.localdate(),
            line_items=[{"product": product, "quantity": Decimal("100"), "rate": Decimal("300")}],
            created_by=self.admin, post=True,
        )
        self.assertEqual(self.detail(invoice), original)
        self.assertEqual(original["products"][0]["product_name"], "Test gift pack")

    def test_repeated_product_lines_are_grouped_and_invoice_percentage_uses_total_cost(self):
        a = self.product("Product A", "6")
        b = self.product("Product B", "100")
        invoice = self.invoice([
            {"product": a, "quantity": Decimal("2"), "rate_charged": Decimal("10")},
            {"product": a, "quantity": Decimal("3"), "rate_charged": Decimal("12")},
            {"product": b, "quantity": Decimal("1"), "rate_charged": Decimal("110")},
        ])
        summary = self.detail(invoice)
        self.assertEqual(len(summary["products"]), 2)
        row = summary["products"][0]
        self.assertEqual(row["base_quantity"], Decimal("5.000"))
        self.assertEqual(row["gross_profit"], Decimal("26.00"))
        self.assertEqual(row["margin_percent"], Decimal("86.7"))
        self.assertEqual(summary["taxable_sales_revenue"], Decimal("166.00"))
        self.assertEqual(summary["taxable_cogs"], Decimal("130.00"))
        self.assertEqual(summary["gross_profit"], Decimal("36.00"))
        self.assertEqual(summary["margin_percent"], Decimal("27.7"))

    def test_master_box_cost_and_quantity_use_pieces(self):
        product = self.product("Boxed product", "6")
        attr = AttributeDefinition.objects.create(code="units_per_master_box", name="Pack", data_type="INTEGER")
        ProductAttributeValue.objects.create(product=product, attribute_definition=attr, value_integer=12)
        invoice = self.invoice([{
            "product": product, "quantity": Decimal("2"), "rate_charged": Decimal("10"),
            "sales_unit_name": "master box", "conversion_factor": Decimal("12"),
        }])
        summary = self.detail(invoice)
        self.assertEqual(summary["products"][0]["base_quantity"], Decimal("24.000"))
        self.assertEqual(summary["taxable_sales_revenue"], Decimal("240.00"))
        self.assertEqual(summary["taxable_cogs"], Decimal("144.00"))
        self.assertEqual(summary["margin_percent"], Decimal("66.7"))

    def test_draft_waits_for_posting_and_post_response_contains_profit(self):
        product = self.product("Draft product", "6")
        invoice = self.invoice(
            [{"product": product, "quantity": Decimal("2"), "rate_charged": Decimal("10")}],
            state=Invoice.STATE_DRAFT,
        )
        self.assertIsNone(self.detail(invoice))
        response = self.client.post(f"/api/invoices/{invoice.pk}/post/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["profit_summary"]["margin_percent"], Decimal("66.7"))

    def test_cancel_response_retains_original_summary_for_reference(self):
        product = self.product("Cancelled product", "6")
        invoice = self.invoice([{"product": product, "quantity": Decimal("2"), "rate_charged": Decimal("10")}])
        original = self.detail(invoice)
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/invoices/{invoice.pk}/cancel/", {"reason": "Test cancellation"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profit_summary"], original)
        self.assertEqual(self.detail(invoice), original)

    def test_credit_note_does_not_restate_original_invoice_summary(self):
        product = self.product("Returned product", "6")
        invoice = self.invoice([{"product": product, "quantity": Decimal("10"), "rate_charged": Decimal("10")}])
        original = self.detail(invoice)
        create_credit_note(
            original_invoice=invoice, reason="Test return", created_by=self.admin,
            line_items=[{"invoice_line_item": invoice.line_items.get(), "product": product, "quantity": Decimal("2")}],
        )
        self.assertEqual(self.detail(invoice), original)

    def test_zero_cost_and_losses(self):
        for name, cost, rate, expected in [("Free", "0", "10", None), ("Loss", "10", "8", Decimal("-20.0"))]:
            with self.subTest(name=name):
                product = self.product(name, cost)
                invoice = self.invoice([{"product": product, "quantity": Decimal("2"), "rate_charged": Decimal(rate)}])
                summary = self.detail(invoice)
                self.assertEqual(summary["margin_percent"], expected)
                self.assertEqual(summary["products"][0]["margin_percent"], expected)

    def test_invoice_list_omits_detailed_profit_breakdown(self):
        product = self.product("Listed product", "6")
        self.invoice([{"product": product, "quantity": Decimal("2"), "rate_charged": Decimal("10")}])
        response = self.client.get("/api/invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("profit_summary", response.data["results"][0])

    def test_unauthenticated_detail_is_rejected(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/invoices/1/")
        self.assertIn(response.status_code, (401, 403))
