from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import AuditLog, Invoice, Payment, PaymentReversal
from billing.services import cancel_invoice, reverse_payment
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

    def test_sale_captures_historical_cost_when_product_cost_changes(self):
        product = self.create_product("Historical Cost Product", stock=5)
        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("HISTORICAL-COST-1001", product, quantity=2, customer=self.customer.pk),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        line = Invoice.objects.get(invoice_number="HISTORICAL-COST-1001").line_items.get()
        product.cost_price = Decimal("95.00")
        product.save(update_fields=["cost_price", "updated_at"])
        line.refresh_from_db()
        self.assertEqual(line.cost_price_snapshot, Decimal("60.00"))
        self.assertEqual(line.cogs_amount, Decimal("120.00"))

    def test_payment_detail_is_read_only(self):
        product = self.create_product("Payment Product", stock=5)
        invoice = Invoice.objects.create(
            invoice_number="PAYMENT-READONLY-1001",
            customer=self.customer,
            payment_type=Invoice.PAYMENT_TYPE_CREDIT,
            total_amount=Decimal("100.00"),
            created_by=self.user,
        )
        payment = Payment.objects.create(customer=self.customer, invoice=invoice, amount=Decimal("10.00"))
        response = self.client.patch(f"/api/payments/{payment.pk}/", {"amount": "99.00"}, format="json")
        self.assertEqual(response.status_code, 405)

    def test_invoice_idempotency_key_returns_original_invoice(self):
        product = self.create_product("Idempotent Product", stock=5)
        payload = self.invoice_payload("IDEMPOTENT-1001", product, quantity=1, payment_type="cash")
        first = self.client.post("/api/invoices/", payload, format="json", HTTP_IDEMPOTENCY_KEY="invoice-test-key")
        second = self.client.post("/api/invoices/", payload, format="json", HTTP_IDEMPOTENCY_KEY="invoice-test-key")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Invoice.objects.filter(invoice_number="IDEMPOTENT-1001").count(), 1)

    def test_credit_limit_is_enforced_before_invoice_creation(self):
        product = self.create_product("Credit Limit Product", stock=5)
        self.customer.credit_limit = Decimal("100.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])
        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("CREDIT-LIMIT-1001", product, customer=self.customer.pk),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("customer", response.data)
        self.assertFalse(Invoice.objects.filter(invoice_number="CREDIT-LIMIT-1001").exists())

    def test_cancellation_preserves_invoice_reverses_stock_and_audits(self):
        product = self.create_product("Cancellation Product", stock=5)
        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("CANCEL-1001", product, quantity=2, customer=self.customer.pk),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        invoice = Invoice.objects.get(invoice_number="CANCEL-1001")
        response = self.client.post(f"/api/invoices/{invoice.pk}/cancel/", {"reason": "Duplicate entry"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        invoice.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(invoice.state, Invoice.STATE_CANCELLED)
        self.assertEqual(product.current_stock, Decimal("5.000"))
        self.assertTrue(AuditLog.objects.filter(action="invoice_cancelled", entity_id=invoice.pk).exists())
        duplicate = self.client.post(f"/api/invoices/{invoice.pk}/cancel/", {"reason": "Again"}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_payment_reversal_is_append_only_and_cannot_repeat(self):
        product = self.create_product("Reversal Product", stock=5)
        invoice = self.invoice_payload("REVERSAL-PAY-1001", product, quantity=1, payment_type="cash")
        response = self.client.post("/api/invoices/", invoice, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        payment = Payment.objects.get(invoice__invoice_number="REVERSAL-PAY-1001")
        response = self.client.post(f"/api/payments/{payment.pk}/reverse/", {"amount": "118.00", "reason": "Bank correction"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PaymentReversal.objects.filter(payment=payment).count(), 1)
        duplicate = self.client.post(f"/api/payments/{payment.pk}/reverse/", {"amount": "1.00", "reason": "Again"}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_posted_invoice_line_and_payment_cannot_be_edited_or_deleted(self):
        product = self.create_product("Immutable Product", stock=5)
        response = self.client.post(
            "/api/invoices/",
            self.invoice_payload("IMMUTABLE-1001", product, quantity=1, payment_type="cash"),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        invoice = Invoice.objects.get(invoice_number="IMMUTABLE-1001")
        line = invoice.line_items.get()
        line.rate_charged = Decimal("1.00")
        with self.assertRaises(ValueError):
            line.save()
        payment = Payment.objects.get(invoice=invoice)
        with self.assertRaises(ValueError):
            payment.delete()

    def test_draft_can_be_created_then_posted_transactionally(self):
        product = self.create_product("Draft Product", stock=5)
        payload = self.invoice_payload("DRAFT-1001", product, quantity=2, customer=self.customer.pk)
        draft = self.client.post("/api/invoices/drafts/", payload, format="json")
        self.assertEqual(draft.status_code, 201, draft.data)
        invoice = Invoice.objects.get(invoice_number="DRAFT-1001")
        self.assertEqual(invoice.state, Invoice.STATE_DRAFT)
        product.refresh_from_db()
        self.assertEqual(product.current_stock, Decimal("5.000"))
        posted = self.client.post(f"/api/invoices/{invoice.pk}/post/", {}, format="json")
        self.assertEqual(posted.status_code, 200, posted.data)
        invoice.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(invoice.state, Invoice.STATE_POSTED)
        self.assertEqual(product.current_stock, Decimal("3.000"))
