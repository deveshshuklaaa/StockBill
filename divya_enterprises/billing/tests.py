from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import CreditNote, Invoice, Payment
from customers.models import Customer


class InvoicePaymentStatusSignalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="adminuser",
            email="admin@test.local",
            password="StrongPass123!",
            role="admin",
        )
        self.customer = Customer.objects.create(
            name="Test Customer",
            contact_info="9999999999",
            customer_type=Customer.CUSTOMER_TYPE_B2C,
            is_regular=True,
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-1001",
            customer=self.customer,
            total_amount=Decimal("1000.00"),
            created_by=self.user,
        )

    def test_payment_status_tracks_payments_and_credit_notes(self):
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, Invoice.PAYMENT_STATUS_CREDIT)

        Payment.objects.create(
            customer=self.customer,
            invoice=self.invoice,
            amount=Decimal("400.00"),
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, Invoice.PAYMENT_STATUS_PARTIALLY_PAID)

        Payment.objects.create(
            customer=self.customer,
            invoice=self.invoice,
            amount=Decimal("600.00"),
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, Invoice.PAYMENT_STATUS_PAID)

        CreditNote.objects.create(
            original_invoice=self.invoice,
            total_amount=Decimal("250.00"),
            reason="Price correction",
            created_by=self.user,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, Invoice.PAYMENT_STATUS_PARTIALLY_PAID)
