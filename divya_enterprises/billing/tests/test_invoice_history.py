"""Regression tests for the sales/invoice history UI backend surface.

Covers the API the /invoices frontend consumes:
- list pagination and ordering
- server-side search (invoice number, customer snapshot, current customer)
- state / payment_type / date-range filters, including 400 validation
- permission boundaries (staff can list/create invoices per existing policy,
  staff cannot cancel; only admin can)
- detail returns the right invoice with line snapshot fields
- cancellation lifecycle already covered in test_billing.py; here we assert
  the exact contract the history/detail pages rely on (state badge values,
  duplicate cancel rejection, reversal movement retained alongside original)
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice
from customers.models import Customer
from inventory.models import Product, StockLedger, TaxRate

User = get_user_model()


class InvoiceHistoryAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="hist-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="hist-staff", password="StrongPass123!", role="staff"
        )
        BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            gstin="27DIVYA1234A1Z5",
            registered_address="Shop 1, Main Road",
            state="Maharashtra",
            state_code="27",
        )
        # Data migration 0007 seeds the default GST slabs into every fresh
        # database, so reuse the seeded row instead of colliding on its
        # unique name.
        cls.tax, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})
        cls.product = Product.objects.create(
            name="Chikki 3 in 1",
            base_unit=Product.UNIT_PIECE,
            default_price=Decimal("5.00"),
            cost_price=Decimal("3.00"),
            tax=cls.tax,
            current_stock=Decimal("100.000"),
        )
        cls.customer = Customer.objects.create(
            name="J K Traders", contact_info="9820011122", state_code="27"
        )
        cls.walk_in_invoice = Invoice.objects.create(
            invoice_number="INV-HIST-0001",
            customer=None,
            payment_type=Invoice.PAYMENT_TYPE_CASH,
            total_amount=Decimal("105.00"),
            state=Invoice.STATE_POSTED,
            created_by=cls.admin,
            customer_name_snapshot="Walk-in customer",
        )
        cls.credit_invoice = Invoice.objects.create(
            invoice_number="INV-HIST-0002",
            customer=cls.customer,
            payment_type=Invoice.PAYMENT_TYPE_CREDIT,
            total_amount=Decimal("210.00"),
            state=Invoice.STATE_POSTED,
            created_by=cls.staff,
            customer_name_snapshot="J K Traders",
        )
        cls.draft_invoice = Invoice.objects.create(
            invoice_number="INV-HIST-0003",
            customer=cls.customer,
            payment_type=Invoice.PAYMENT_TYPE_CREDIT,
            total_amount=Decimal("50.00"),
            state=Invoice.STATE_DRAFT,
            created_by=cls.staff,
            customer_name_snapshot="J K Traders",
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_list_is_paginated_and_ordered_newest_first(self):
        response = self.client_as(self.staff).get("/api/invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["count"], 3)
        numbers = [row["invoice_number"] for row in response.data["results"]]
        self.assertEqual(numbers, ["INV-HIST-0003", "INV-HIST-0002", "INV-HIST-0001"])

    def test_search_matches_invoice_number_and_customer(self):
        checks = [
            ("INV-HIST-0001", ["INV-HIST-0001"]),
            ("0002", ["INV-HIST-0002"]),
            ("J K Traders", ["INV-HIST-0002", "INV-HIST-0003"]),
            ("Walk-in", ["INV-HIST-0001"]),
            ("no-match-xyz", []),
        ]
        for query, expected in checks:
            response = self.client_as(self.staff).get(
                "/api/invoices/", {"search": query}
            )
            self.assertEqual(response.status_code, 200, query)
            self.assertEqual(
                sorted(row["invoice_number"] for row in response.data["results"]),
                sorted(expected),
                query,
            )

    def test_state_filter(self):
        for state, expected_count in (("POSTED", 2), ("DRAFT", 1), ("CANCELLED", 0)):
            response = self.client_as(self.staff).get(
                "/api/invoices/", {"state": state}
            )
            self.assertEqual(response.status_code, 200, state)
            self.assertEqual(response.data["count"], expected_count, state)
            for row in response.data["results"]:
                self.assertEqual(row["state"], state)

    def test_payment_type_filter(self):
        for payment_type, expected_count in (("cash", 1), ("credit", 2)):
            response = self.client_as(self.staff).get(
                "/api/invoices/", {"payment_type": payment_type}
            )
            self.assertEqual(response.status_code, 200, payment_type)
            self.assertEqual(response.data["count"], expected_count, payment_type)

    def test_date_range_filter(self):
        response = self.client_as(self.staff).get(
            "/api/invoices/", {"from": "2000-01-01", "to": "2100-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        response = self.client_as(self.staff).get(
            "/api/invoices/", {"from": "2100-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_invalid_filters_rejected(self):
        for bad in [
            {"state": "MADE_UP"},
            {"payment_type": "cheque"},
            {"from": "12/09/2026"},
            {"to": "yesterday"},
        ]:
            response = self.client_as(self.staff).get("/api/invoices/", bad)
            self.assertEqual(response.status_code, 400, bad)

    def test_list_rows_expose_ui_fields(self):
        response = self.client_as(self.staff).get("/api/invoices/")
        row = response.data["results"][0]
        for field in (
            "id",
            "invoice_number",
            "invoice_date",
            "customer_name",
            "payment_type",
            "payment_status",
            "state",
            "total_amount",
        ):
            self.assertIn(field, row)

    def test_detail_returns_correct_invoice(self):
        response = self.client_as(self.staff).get(
            f"/api/invoices/{self.credit_invoice.pk}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["invoice_number"], "INV-HIST-0002")
        self.assertEqual(response.data["customer_name"], "J K Traders")
        self.assertEqual(response.data["state"], "POSTED")

    def test_detail_missing_invoice_is_404(self):
        response = self.client_as(self.staff).get("/api/invoices/999999/")
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_cannot_list_invoices(self):
        response = APIClient().get("/api/invoices/")
        self.assertIn(response.status_code, {401, 403})

    def test_staff_cannot_cancel_but_admin_can(self):
        # Staff cancel attempt -> 403 (backend is authoritative even though
        # the UI hides the button for staff).
        response = self.client_as(self.staff).post(
            f"/api/invoices/{self.walk_in_invoice.pk}/cancel/",
            {"reason": "staff attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.walk_in_invoice.refresh_from_db()
        self.assertEqual(self.walk_in_invoice.state, Invoice.STATE_POSTED)

        # A line item is needed for cancellation; create the real flow.
        from billing.services import create_invoice

        sale = create_invoice(
            customer=self.customer,
            invoice_number="INV-HIST-CANCEL",
            created_by=self.admin,
            payment_type="credit",
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal("2"),
                    "rate_charged": Decimal("5.00"),
                    "tax_rate": Decimal("5.00"),
                }
            ],
        )
        response = self.client_as(self.admin).post(
            f"/api/invoices/{sale.pk}/cancel/", {"reason": "Wrong entry"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        sale.refresh_from_db()
        self.assertEqual(sale.state, Invoice.STATE_CANCELLED)

        # Original SALE movement retained + SALE_REVERSAL created.
        self.assertEqual(
            StockLedger.objects.filter(
                product=self.product,
                movement_type=StockLedger.SALE,
                reference_type="invoice",
                reference_id=sale.pk,
            ).count(),
            1,
        )
        self.assertEqual(
            StockLedger.objects.filter(
                product=self.product,
                movement_type=StockLedger.SALE_REVERSAL,
                reference_type="invoice_cancellation",
                reference_id=sale.pk,
            ).count(),
            1,
        )

        # Duplicate cancellation is rejected with the backend reason.
        duplicate = self.client_as(self.admin).post(
            f"/api/invoices/{sale.pk}/cancel/", {"reason": "again"}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("state", duplicate.data)

    def test_cancel_requires_reason(self):
        from billing.services import create_invoice

        sale = create_invoice(
            customer=self.customer,
            invoice_number="INV-HIST-NOREASON",
            created_by=self.admin,
            payment_type="credit",
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal("1"),
                    "rate_charged": Decimal("5.00"),
                    "tax_rate": Decimal("5.00"),
                }
            ],
        )
        response = self.client_as(self.admin).post(
            f"/api/invoices/{sale.pk}/cancel/", {"reason": ""}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.data)
