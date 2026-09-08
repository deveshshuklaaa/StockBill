from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import Invoice, Payment
from customers.models import Customer
from inventory.models import Product


class ReportingEndpointTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="report-admin",
            password="StrongPass123!",
            role="admin",
        )
        self.staff = user_model.objects.create_user(
            username="report-staff",
            password="StrongPass123!",
            role="staff",
        )
        self.customer = Customer.objects.create(name="Report Customer", is_regular=True)
        self.product = self.create_product("Report Product", stock=20, cost=60, price=100)
        self.other_product = self.create_product("Other Product", stock=20, cost=40, price=80)
        self.today = date.today().isoformat()

    def create_product(self, name, stock, cost, price):
        return Product.objects.create(
            name=name,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            current_stock=stock,
            cost_price=cost,
            default_price=price,
            tax_slab=Product.TAX_18,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def invoice(self, client, number, product, quantity, payment_type="credit"):
        response = client.post(
            "/api/invoices/",
            {
                "invoice_number": number,
                "customer": self.customer.pk,
                "payment_type": payment_type,
                "line_items": [
                    {
                        "product": product.pk,
                        "quantity": str(quantity),
                        "rate_charged": str(product.default_price),
                        "tax_rate": product.tax_slab,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Invoice.objects.get(invoice_number=number)

    def test_daily_sales_report_splits_cash_credit_and_tax(self):
        client = self.client_as(self.admin)
        self.invoice(client, "REPORT-CASH", self.product, 1, payment_type="cash")
        self.invoice(client, "REPORT-CREDIT", self.other_product, 2, payment_type="credit")

        response = client.get(f"/api/reports/daily-sales/?date={self.today}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["invoice_count"], 2)
        self.assertEqual(response.data["invoice_count_by_payment_type"], {"cash": 1, "credit": 1})
        self.assertEqual(response.data["sold_cash_today"], Decimal("118.00"))
        self.assertEqual(response.data["sold_on_credit_today"], Decimal("188.80"))
        self.assertEqual(response.data["cash_collected_today"], Decimal("118.00"))
        self.assertEqual(response.data["total_revenue"], Decimal("306.80"))
        self.assertEqual(response.data["tax_collected_by_slab"]["18"], Decimal("46.80"))

    def test_prior_day_credit_invoice_payment_counts_as_today_cash_collection_only(self):
        client = self.client_as(self.admin)
        invoice = self.invoice(client, "REPORT-PRIOR-CREDIT", self.product, 1)
        yesterday = date.today() - timedelta(days=1)
        Invoice.objects.filter(pk=invoice.pk).update(invoice_date=yesterday)
        payment = Payment.objects.create(customer=self.customer, invoice=invoice, amount=invoice.total_amount, payment_date=date.today())

        response = client.get(f"/api/reports/daily-sales/?date={self.today}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cash_collected_today"], Decimal("118.00"))
        self.assertEqual(response.data["sold_on_credit_today"], Decimal("0.00"))
        self.assertEqual(response.data["sold_cash_today"], Decimal("0.00"))

    def test_same_day_credit_sale_and_payment_counts_in_both_distinct_metrics(self):
        client = self.client_as(self.admin)
        invoice = self.invoice(client, "REPORT-SAME-DAY-CREDIT", self.product, 1)
        Payment.objects.create(customer=self.customer, invoice=invoice, amount=invoice.total_amount)

        response = client.get(f"/api/reports/daily-sales/?date={self.today}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sold_on_credit_today"], Decimal("118.00"))
        self.assertEqual(response.data["sold_cash_today"], Decimal("0.00"))
        self.assertEqual(response.data["cash_collected_today"], Decimal("118.00"))

    def test_stock_valuation_hides_cost_for_staff_and_includes_it_for_admin(self):
        admin_response = self.client_as(self.admin).get("/api/reports/stock-valuation/")
        staff_response = self.client_as(self.staff).get("/api/reports/stock-valuation/")

        self.assertEqual(admin_response.status_code, 200)
        self.assertIn("total_valuation_cost_price", admin_response.data)
        self.assertIn("stock_value_cost_price", admin_response.data["products"][0])
        self.assertEqual(staff_response.status_code, 200)
        self.assertNotIn("total_valuation_cost_price", staff_response.data)
        self.assertNotIn("stock_value_cost_price", staff_response.data["products"][0])

    def test_profit_loss_reduces_revenue_and_cogs_for_credit_note(self):
        client = self.client_as(self.admin)
        invoice = self.invoice(client, "REPORT-PROFIT", self.product, 2)
        line = invoice.line_items.get()
        response = client.post(
            "/api/credit-notes/",
            {
                "original_invoice": invoice.pk,
                "reason": "Returned item",
                "line_items": [
                    {"invoice_line_item": line.pk, "product": self.product.pk, "quantity": "1"}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        response = client.get(f"/api/reports/profit-loss/?from={self.today}&to={self.today}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["revenue"], Decimal("118.00"))
        self.assertEqual(response.data["cost_of_goods_sold"], Decimal("60.00"))
        self.assertEqual(response.data["net_profit"], Decimal("58.00"))
        self.assertIn("current cost_price", response.data["cost_price_assumption"])

    def test_staff_is_forbidden_from_profit_loss_report(self):
        response = self.client_as(self.staff).get(
            f"/api/reports/profit-loss/?from={self.today}&to={self.today}"
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("revenue", response.data)
        self.assertNotIn("cost_of_goods_sold", response.data)

    def test_top_products_excludes_fully_credit_noted_quantity(self):
        client = self.client_as(self.admin)
        credited_invoice = self.invoice(client, "REPORT-TOP-CREDIT", self.product, 3)
        kept_invoice = self.invoice(client, "REPORT-TOP-KEPT", self.other_product, 2)
        credited_line = credited_invoice.line_items.get()
        response = client.post(
            "/api/credit-notes/",
            {
                "original_invoice": credited_invoice.pk,
                "reason": "Full return",
                "line_items": [
                    {"invoice_line_item": credited_line.pk, "product": self.product.pk, "quantity": "3"}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        response = client.get(
            f"/api/reports/top-products/?from={self.today}&to={self.today}&sort_by=quantity&limit=10"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["products"]), 1)
        self.assertEqual(response.data["products"][0]["product_id"], kept_invoice.line_items.get().product_id)
        self.assertEqual(response.data["products"][0]["total_quantity"], Decimal("2.000"))

    def test_customer_report_reuses_outstanding_balance(self):
        client = self.client_as(self.admin)
        self.invoice(client, "REPORT-CUSTOMER", self.product, 1)

        response = client.get(f"/api/customers/{self.customer.pk}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["invoices"]), 1)
        self.assertEqual(response.data["outstanding_balance"], Decimal("118.00"))
