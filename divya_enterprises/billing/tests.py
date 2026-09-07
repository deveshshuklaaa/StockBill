from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import Invoice, Payment
from customers.models import Customer
from inventory.models import Product


class TransactionalBillingTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="adminuser",
            email="admin@test.local",
            password="StrongPass123!",
            role="admin",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.customer = Customer.objects.create(
            name="Test Customer",
            contact_info="9999999999",
            customer_type=Customer.CUSTOMER_TYPE_B2C,
            is_regular=True,
        )

    def create_product(self, name, stock=10):
        return Product.objects.create(
            name=name,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=100,
            cost_price=60,
            tax_slab=Product.TAX_18,
            current_stock=stock,
        )

    def invoice_payload(self, invoice_number, product, quantity=1, customer=None, payment_type="credit"):
        return {
            "invoice_number": invoice_number,
            "customer": customer,
            "payment_type": payment_type,
            "line_items": [
                {
                    "product": product.pk,
                    "quantity": str(quantity),
                    "rate_charged": "100.00",
                    "tax_rate": product.tax_slab,
                }
            ],
        }

    def test_cash_sale_deducts_stock_and_creates_paid_ledger_entry(self):
        product = self.create_product("Cash Product", stock=5)

        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("CASH-1001", product, quantity=2, payment_type="cash"),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        product.refresh_from_db()
        invoice = Invoice.objects.get(invoice_number="CASH-1001")
        self.assertEqual(product.current_stock, Decimal("3.000"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PAID)
        self.assertEqual(Payment.objects.get(invoice=invoice).amount, Decimal("236.00"))

    def test_credit_sale_deducts_stock_and_stays_credit_without_payment(self):
        product = self.create_product("Credit Product", stock=5)

        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("CREDIT-1001", product, quantity=2, customer=self.customer.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        product.refresh_from_db()
        invoice = Invoice.objects.get(invoice_number="CREDIT-1001")
        self.assertEqual(product.current_stock, Decimal("3.000"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_CREDIT)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())

    def test_credit_sale_requires_registered_customer(self):
        product = self.create_product("Walk-in Credit Product")

        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("INVALID-1001", product, payment_type="credit"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("customer", response.data)
        self.assertFalse(Invoice.objects.filter(invoice_number="INVALID-1001").exists())

    def test_multi_line_stock_failure_does_not_partially_deduct_stock(self):
        first_product = self.create_product("First Product", stock=5)
        second_product = self.create_product("Second Product", stock=1)
        payload = self.invoice_payload("ROLLBACK-1001", first_product, quantity=2, customer=self.customer.pk)
        payload["line_items"].append(
            {
                "product": second_product.pk,
                "quantity": "2",
                "rate_charged": "100.00",
                "tax_rate": second_product.tax_slab,
            }
        )

        response = self.client.post("/api/invoices/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        first_product.refresh_from_db()
        second_product.refresh_from_db()
        self.assertEqual(first_product.current_stock, Decimal("5.000"))
        self.assertEqual(second_product.current_stock, Decimal("1.000"))
        self.assertFalse(Invoice.objects.filter(invoice_number="ROLLBACK-1001").exists())

    def test_partial_credit_note_restores_stock_and_reduces_customer_balance_only_for_target_invoice(self):
        product = self.create_product("Reversible Product", stock=10)
        unrelated_product = self.create_product("Unrelated Product", stock=10)
        invoice_response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("REVERSAL-1001", product, quantity=4, customer=self.customer.pk),
            format="json",
        )
        unrelated_response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("UNRELATED-1001", unrelated_product, quantity=1, customer=self.customer.pk),
            format="json",
        )
        self.assertEqual(invoice_response.status_code, 201, invoice_response.data)
        self.assertEqual(unrelated_response.status_code, 201, unrelated_response.data)

        invoice = Invoice.objects.get(invoice_number="REVERSAL-1001")
        unrelated_invoice = Invoice.objects.get(invoice_number="UNRELATED-1001")
        original_line = invoice.line_items.get()
        response = self.client.post(
            "/api/credit-notes/",
            {
                "original_invoice": invoice.pk,
                "reason": "Partial return",
                "line_items": [
                    {
                        "invoice_line_item": original_line.pk,
                        "product": product.pk,
                        "quantity": "2",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        product.refresh_from_db()
        invoice.refresh_from_db()
        unrelated_invoice.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(product.current_stock, Decimal("8.000"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_CREDIT)
        self.assertEqual(unrelated_invoice.payment_status, Invoice.PAYMENT_STATUS_CREDIT)
        self.assertEqual(self.customer.outstanding_balance, Decimal("354.00"))
