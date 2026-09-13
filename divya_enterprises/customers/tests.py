"""Regression tests for the customer financial-account backend surface.

Covers the API the /customers and /customers/:id frontend consumes:
- list pagination, server-side search, and is_active filtering (incl. 400)
- detail returns the correct customer with authoritative balances
- DELETE archives instead of hard-deleting (history stays intact)
- customer report: invoices/payments belong only to that customer
- statement: backend-computed running balance (invoice/payment/credit note/
  payment reversal/opening) that reconciles with outstanding_balance
- payment creation through the API: validation (positive amount, invoice
  ownership, posted invoice), payment history, reversal, duplicate reversal
- credit-limit enforcement at both create and draft->post time
- permission boundaries (staff read-only on customers, staff can record
  payments, only admin reverses/archives)
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import AuditLog, BusinessProfile, CreditNote, Invoice, InvoiceLineItem, Payment, PaymentReversal
from customers.models import Customer
from inventory.models import Product, TaxRate

User = get_user_model()


class CustomerAccountTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="cust-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="cust-staff", password="StrongPass123!", role="staff"
        )
        BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            gstin="27DIVYA1234A1Z5",
            registered_address="Shop 1, Main Road",
            state="Maharashtra",
            state_code="27",
        )
        cls.tax, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})
        cls.product = Product.objects.create(
            name="Chikki 3 in 1",
            base_unit=Product.UNIT_PIECE,
            default_price=Decimal("100.00"),
            cost_price=Decimal("60.00"),
            tax=cls.tax,
            current_stock=Decimal("100.000"),
        )
        cls.customer = Customer.objects.create(
            name="J K Traders",
            contact_info="9820011122",
            gstin="27JKTRADERS1A1Z5",
            state="Maharashtra",
            state_code="27",
        )
        cls.other_customer = Customer.objects.create(
            name="Sharma Store", contact_info="9811112233", state_code="27"
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def create_posted_invoice(self, customer, invoice_number, amount, payment_type="credit"):
        return Invoice.objects.create(
            invoice_number=invoice_number,
            customer=customer,
            payment_type=payment_type,
            total_amount=Decimal(amount),
            state=Invoice.STATE_POSTED,
            created_by=self.admin,
        )

    # --- list: search / pagination / active filter ---

    def test_customer_list_search_matches_name_phone_gstin(self):
        response = self.client.get("/api/customers/", {"search": "J K"})
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(all("J K" in row["name"] for row in results))
        self.assertTrue(any(row["name"] == "J K Traders" for row in results))

        response = self.client.get("/api/customers/", {"search": "27JKTRADERS1A1Z5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in response.data["results"]], ["J K Traders"])

        response = self.client.get("/api/customers/", {"search": "9820011122"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in response.data["results"]], ["J K Traders"])

    def test_customer_list_rejects_invalid_active_filter(self):
        response = self.client.get("/api/customers/", {"is_active": "maybe"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("is_active", response.data)

    def test_customer_list_active_filter_and_pagination(self):
        Customer.objects.create(name="Archived Customer", is_active=False)
        for index in range(60):
            Customer.objects.create(name=f"Search Page Customer {index:02d}")

        active_response = self.client.get("/api/customers/", {"is_active": "true", "search": "Search Page Customer"})
        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(active_response.data["count"], 60)
        self.assertEqual(len(active_response.data["results"]), 25)
        self.assertTrue(all(row["is_active"] for row in active_response.data["results"]))

        page2 = self.client.get(active_response.data["next"].replace("http://testserver", ""))
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(len(page2.data["results"]), 25)
        self.assertNotEqual(
            page2.data["results"][0]["id"], active_response.data["results"][0]["id"]
        )

    def test_customer_list_includes_authoritative_balances(self):
        self.create_posted_invoice(self.customer, "INV-C-0001", "500.00")
        response = self.client.get("/api/customers/", {"search": "J K Traders"})
        row = response.data["results"][0]
        self.assertEqual(row["outstanding_balance"], Decimal("500.00"))
        self.assertEqual(row["available_credit"], Decimal("-500.00"))

    # --- detail / archive ---

    def test_customer_detail_returns_correct_customer_with_balances(self):
        self.create_posted_invoice(self.customer, "INV-C-0002", "300.00")
        response = self.client.get(f"/api/customers/{self.customer.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "J K Traders")
        self.assertEqual(response.data["outstanding_balance"], Decimal("300.00"))
        self.assertEqual(response.data["available_credit"], Decimal("-300.00"))
        self.assertEqual(response.data["gstin"], "27JKTRADERS1A1Z5")

    def test_customer_delete_archives_and_preserves_history(self):
        invoice = self.create_posted_invoice(self.customer, "INV-C-0003", "100.00")
        response = self.client.delete(f"/api/customers/{self.customer.pk}/")
        self.assertEqual(response.status_code, 204)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="customer_archived", entity_type="Customer", entity_id=self.customer.pk
            ).exists()
        )
        # Reactivation keeps the same row and history.
        patch = self.client.patch(f"/api/customers/{self.customer.pk}/", {"is_active": True}, format="json")
        self.assertEqual(patch.status_code, 200)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_customer_create_and_update_are_audited(self):
        response = self.client.post(
            "/api/customers/",
            {"name": "Audit Customer", "contact_info": "9000000000"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            AuditLog.objects.filter(
                action="customer_created", entity_type="Customer", entity_id=response.data["id"]
            ).exists()
        )
        update = self.client.patch(
            f"/api/customers/{response.data['id']}/", {"contact_info": "9111111111"}, format="json"
        )
        self.assertEqual(update.status_code, 200)
        self.assertTrue(
            AuditLog.objects.filter(
                action="customer_updated", entity_type="Customer", entity_id=response.data["id"]
            ).exists()
        )

    # --- report: scoping and authoritative statement ---

    def test_customer_report_scopes_invoices_and_payments_to_customer(self):
        mine = self.create_posted_invoice(self.customer, "INV-C-0004", "400.00")
        self.create_posted_invoice(self.other_customer, "INV-O-0001", "700.00")
        Payment.objects.create(
            customer=self.customer, invoice=mine, amount=Decimal("150.00")
        )
        Payment.objects.create(
            customer=self.other_customer, amount=Decimal("50.00")
        )

        response = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["invoice_number"] for row in response.data["invoices"]], ["INV-C-0004"]
        )
        self.assertEqual(len(response.data["payments"]), 1)
        self.assertEqual(response.data["payments"][0]["amount"], Decimal("150.00"))
        self.assertEqual(response.data["payments"][0]["invoice_number"], "INV-C-0004")
        self.assertEqual(response.data["outstanding_balance"], Decimal("250.00"))
        self.assertEqual(response.data["available_credit"], Decimal("-250.00"))

    def test_customer_report_statement_reconciles_running_balance(self):
        self.customer.opening_balance = Decimal("100.00")
        self.customer.save(update_fields=["opening_balance", "updated_at"])
        invoice = self.create_posted_invoice(self.customer, "INV-C-0005", "500.00")
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            product=self.product,
            quantity=Decimal("5.000"),
            rate_charged=Decimal("100.00"),
            line_total=Decimal("500.00"),
        )
        payment = Payment.objects.create(
            customer=self.customer, invoice=invoice, amount=Decimal("200.00")
        )
        CreditNote.objects.create(
            original_invoice=invoice, total_amount=Decimal("100.00"), created_by=self.admin
        )
        PaymentReversal.objects.create(
            payment=payment,
            amount=Decimal("50.00"),
            reason="Bank correction",
            reversed_by=self.admin,
        )

        response = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(response.status_code, 200)
        statement = response.data["statement"]
        types = [row["type"] for row in statement]
        self.assertEqual(types.count("OPENING"), 1)
        self.assertEqual(types.count("INVOICE"), 1)
        self.assertEqual(types.count("PAYMENT"), 1)
        self.assertEqual(types.count("PAYMENT_REVERSAL"), 1)
        self.assertEqual(types.count("CREDIT_NOTE"), 1)

        # Authoritative reconciliation: statement closing balance == outstanding.
        closing = response.data["statement_closing_balance"]
        self.assertEqual(closing, response.data["outstanding_balance"])
        # opening 100 + invoice 500 - payment 200 + reversal 50 - credit note 100
        self.assertEqual(closing, Decimal("350.00"))
        self.assertEqual(statement[-1]["balance"], Decimal("350.00"))

    def test_customer_report_ignores_cancelled_and_draft_invoices_in_statement(self):
        self.create_posted_invoice(self.customer, "INV-C-0006", "300.00")
        Invoice.objects.create(
            invoice_number="INV-C-0007",
            customer=self.customer,
            payment_type="credit",
            total_amount=Decimal("90.00"),
            state=Invoice.STATE_CANCELLED,
            created_by=self.admin,
        )
        Invoice.objects.create(
            invoice_number="INV-C-0008",
            customer=self.customer,
            payment_type="credit",
            total_amount=Decimal("70.00"),
            state=Invoice.STATE_DRAFT,
            created_by=self.admin,
        )

        response = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        statement = response.data["statement"]
        self.assertEqual([row["reference"] for row in statement], ["INV-C-0006"])
        self.assertEqual(response.data["outstanding_balance"], Decimal("300.00"))

    # --- payments: creation, history, reversal ---

    def test_payment_creation_validation_and_history(self):
        invoice = self.create_posted_invoice(self.customer, "INV-C-0009", "600.00")
        zero = self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "amount": "0.00"},
            format="json",
        )
        self.assertEqual(zero.status_code, 400)
        self.assertIn("amount", zero.data)

        wrong_invoice = self.create_posted_invoice(self.other_customer, "INV-O-0002", "50.00")
        mismatched = self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": wrong_invoice.pk, "amount": "10.00"},
            format="json",
        )
        self.assertEqual(mismatched.status_code, 400)
        self.assertIn("invoice", mismatched.data)

        draft = Invoice.objects.create(
            invoice_number="INV-C-0010",
            customer=self.customer,
            payment_type="credit",
            total_amount=Decimal("40.00"),
            state=Invoice.STATE_DRAFT,
            created_by=self.admin,
        )
        against_draft = self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": draft.pk, "amount": "10.00"},
            format="json",
        )
        self.assertEqual(against_draft.status_code, 400)

        created = self.client.post(
            "/api/payments/",
            {
                "customer": self.customer.pk,
                "invoice": invoice.pk,
                "amount": "150.00",
                "payment_method": "upi",
                "reference_number": "UPI-REF-77",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["payment_method"], "upi")
        self.assertEqual(created.data["reference_number"], "UPI-REF-77")
        self.assertEqual(created.data["reversed_amount"], Decimal("0.00"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="payment_received", entity_id=created.data["id"], user=self.admin
            ).exists()
        )

        # Payment history filter returns only that customer's payments.
        history = self.client.get("/api/payments/", {"customer": self.customer.pk})
        self.assertEqual(history.status_code, 200)
        amounts = [Decimal(str(row["amount"])) for row in history.data["results"]]
        self.assertEqual(amounts, [Decimal("150.00")])
        self.assertEqual(history.data["results"][0]["invoice_number"], "INV-C-0009")

        # Outstanding reflects the payment (backend-authoritative).
        report = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.data["outstanding_balance"], Decimal("450.00"))

    def test_payment_history_filters_by_method_and_date(self):
        invoice = self.create_posted_invoice(self.customer, "INV-C-0011", "100.00")
        self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": invoice.pk, "amount": "30.00", "payment_method": "cash"},
            format="json",
        )
        self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": invoice.pk, "amount": "20.00", "payment_method": "upi"},
            format="json",
        )

        upi = self.client.get("/api/payments/", {"customer": self.customer.pk, "payment_method": "upi"})
        self.assertEqual(upi.status_code, 200)
        self.assertEqual([Decimal(str(row["amount"])) for row in upi.data["results"]], [Decimal("20.00")])

        today = date.today().isoformat()
        ranged = self.client.get("/api/payments/", {"from": today, "to": today})
        self.assertEqual(ranged.status_code, 200)
        self.assertEqual(ranged.data["count"], 2)

        invalid = self.client.get("/api/payments/", {"payment_method": "gold"})
        self.assertEqual(invalid.status_code, 400)
        invalid_date = self.client.get("/api/payments/", {"from": "13/09/2026"})
        self.assertEqual(invalid_date.status_code, 400)

    def test_payment_reversal_updates_balances_and_blocks_duplicates(self):
        invoice = self.create_posted_invoice(self.customer, "INV-C-0012", "300.00")
        created = self.client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": invoice.pk, "amount": "100.00"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        payment_id = created.data["id"]

        reversal = self.client.post(
            f"/api/payments/{payment_id}/reverse/",
            {"amount": "40.00", "reason": "Entered twice"},
            format="json",
        )
        self.assertEqual(reversal.status_code, 201, reversal.data)
        self.assertTrue(
            AuditLog.objects.filter(
                action="payment_reversed", entity_id=payment_id, user=self.admin
            ).exists()
        )

        # History shows the reversal; payment itself is never deleted.
        history = self.client.get("/api/payments/", {"customer": self.customer.pk})
        row = history.data["results"][0]
        self.assertEqual(row["id"], payment_id)
        self.assertEqual(row["reversed_amount"], Decimal("40.00"))

        # Outstanding recalculated by the backend: 300 - 100 + 40 = 240.
        report = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.data["outstanding_balance"], Decimal("240.00"))

        exceed = self.client.post(
            f"/api/payments/{payment_id}/reverse/",
            {"amount": "61.00", "reason": "Too much"},
            format="json",
        )
        self.assertEqual(exceed.status_code, 400)
        self.assertEqual(
            PaymentReversal.objects.filter(payment_id=payment_id).count(), 1
        )

    # --- credit limit ---

    def test_credit_limit_blocks_credit_invoice_creation(self):
        self.customer.credit_limit = Decimal("100.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])
        response = self.client.post(
            "/api/invoices/",
            {
                "invoice_number": "INV-CREDIT-LIMIT-1",
                "customer": self.customer.pk,
                "payment_type": "credit",
                "line_items": [
                    {
                        "product": self.product.pk,
                        "quantity": "2",
                        "rate_charged": "100.00",
                        "tax_rate": self.tax.rate,
                    }
                ],
                "place_of_supply": "27",
                "tax_mode": "exclusive",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("customer", response.data)
        self.assertFalse(Invoice.objects.filter(invoice_number="INV-CREDIT-LIMIT-1").exists())

    def test_credit_limit_blocked_at_draft_posting(self):
        # Draft creation succeeds under a high limit; the limit is then
        # tightened so posting must re-check available credit.
        self.customer.credit_limit = Decimal("10000.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])
        draft = self.client.post(
            "/api/invoices/drafts/",
            {
                "invoice_number": "INV-CREDIT-LIMIT-2",
                "customer": self.customer.pk,
                "payment_type": "credit",
                "line_items": [
                    {
                        "product": self.product.pk,
                        "quantity": "2",
                        "rate_charged": "100.00",
                        "tax_rate": self.tax.rate,
                    }
                ],
                "place_of_supply": "27",
                "tax_mode": "exclusive",
            },
            format="json",
        )
        self.assertEqual(draft.status_code, 201, draft.data)
        self.customer.credit_limit = Decimal("100.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])

        posted = self.client.post(f"/api/invoices/{draft.data['id']}/post/", {}, format="json")
        self.assertEqual(posted.status_code, 400)
        self.assertIn("customer", posted.data)
        invoice = Invoice.objects.get(invoice_number="INV-CREDIT-LIMIT-2")
        self.assertEqual(invoice.state, Invoice.STATE_DRAFT)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("100.000"))

    def test_credit_limit_restored_after_invoice_cancellation(self):
        self.customer.credit_limit = Decimal("1000.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])
        invoice = self.create_posted_invoice(self.customer, "INV-CREDIT-LIMIT-3", "800.00")

        report = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.data["outstanding_balance"], Decimal("800.00"))
        self.assertEqual(report.data["available_credit"], Decimal("200.00"))

        cancelled = self.client.post(
            f"/api/invoices/{invoice.pk}/cancel/", {"reason": "Wrong entry"}, format="json"
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)

        report = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.data["outstanding_balance"], Decimal("0.00"))
        self.assertEqual(report.data["available_credit"], Decimal("1000.00"))

    def test_cash_sales_bypass_credit_limit(self):
        self.customer.credit_limit = Decimal("1.00")
        self.customer.save(update_fields=["credit_limit", "updated_at"])
        response = self.client.post(
            "/api/invoices/",
            {
                "invoice_number": "INV-CASH-LIMIT",
                "customer": self.customer.pk,
                "payment_type": "cash",
                "line_items": [
                    {
                        "product": self.product.pk,
                        "quantity": "2",
                        "rate_charged": "100.00",
                        "tax_rate": self.tax.rate,
                    }
                ],
                "place_of_supply": "27",
                "tax_mode": "exclusive",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        invoice = Invoice.objects.get(invoice_number="INV-CASH-LIMIT")
        self.assertTrue(Payment.objects.filter(invoice=invoice).exists())
        # Cash sale is paid immediately; outstanding stays zero.
        report = self.client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.data["outstanding_balance"], Decimal("0.00"))

    # --- permissions ---

    def test_staff_customer_permissions_are_read_only(self):
        staff_client = self.client_as(self.staff)
        listed = staff_client.get("/api/customers/")
        self.assertEqual(listed.status_code, 200)

        created = staff_client.post(
            "/api/customers/", {"name": "Staff Customer"}, format="json"
        )
        self.assertEqual(created.status_code, 403)

        patched = staff_client.patch(
            f"/api/customers/{self.customer.pk}/", {"name": "Changed"}, format="json"
        )
        self.assertEqual(patched.status_code, 403)

        deleted = staff_client.delete(f"/api/customers/{self.customer.pk}/")
        self.assertEqual(deleted.status_code, 403)

        report = staff_client.get(f"/api/customers/{self.customer.pk}/report/")
        self.assertEqual(report.status_code, 200)

    def test_staff_can_record_payments_but_only_admin_reverses(self):
        invoice = self.create_posted_invoice(self.customer, "INV-PERM-0001", "200.00")
        staff_client = self.client_as(self.staff)
        created = staff_client.post(
            "/api/payments/",
            {"customer": self.customer.pk, "invoice": invoice.pk, "amount": "50.00"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        reversed_by_staff = staff_client.post(
            f"/api/payments/{created.data['id']}/reverse/",
            {"amount": "10.00", "reason": "Staff attempt"},
            format="json",
        )
        self.assertEqual(reversed_by_staff.status_code, 403)
        self.assertEqual(PaymentReversal.objects.count(), 0)

    def test_payment_and_report_require_authentication(self):
        anonymous = APIClient()
        self.assertIn(anonymous.get("/api/customers/").status_code, {401, 403})
        self.assertIn(anonymous.get("/api/payments/").status_code, {401, 403})
        self.assertIn(
            anonymous.get(f"/api/customers/{self.customer.pk}/report/").status_code, {401, 403}
        )
