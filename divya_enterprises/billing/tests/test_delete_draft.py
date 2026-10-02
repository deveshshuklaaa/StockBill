from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import AuditLog, BusinessProfile, Invoice, InvoiceLineItem, Payment
from billing.services import cancel_invoice
from customers.models import Customer
from inventory.models import InventoryBalance, Product, StockLedger, TaxRate
from inventory.services import ensure_inventory_balance, get_default_warehouse


class DeleteDraftInvoiceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            email="admin@test.local",
            password="AdminPass123!",
            role="admin",
        )
        self.staff1 = User.objects.create_user(
            username="staff_one",
            email="staff1@test.local",
            password="StaffPass123!",
            role="staff",
        )
        self.staff2 = User.objects.create_user(
            username="staff_two",
            email="staff2@test.local",
            password="StaffPass123!",
            role="staff",
        )

        self.tax_18 = TaxRate.objects.create(name="18%", rate=Decimal("18.00"))
        self.warehouse = get_default_warehouse()
        self.product = Product.objects.create(
            name="Test Product 1",
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=100,
            cost_price=60,
            tax=self.tax_18,
            current_stock=20,
        )
        self.product_balance = ensure_inventory_balance(product=self.product, warehouse=self.warehouse)

        self.customer = Customer.objects.create(
            name="Test Customer",
            contact_info="9876543210",
            customer_type=Customer.CUSTOMER_TYPE_B2B,
            is_regular=True,
            state_code="29",
            gstin="29TESTCUST1234Z",
            credit_limit=Decimal("50000.00"),
        )

        BusinessProfile.objects.get_or_create(
            business_name="StockBill Enterprises",
            defaults={
                "gstin": "29AABCS1429B1ZB",
                "registered_address": "Bangalore, Karnataka",
                "state": "Karnataka",
                "state_code": "29",
            },
        )

    def _client_for(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def _create_draft(self, created_by, invoice_number="DR-TEST-001", qty=5):
        client = self._client_for(created_by)
        payload = {
            "invoice_number": invoice_number,
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [
                {
                    "product": self.product.pk,
                    "quantity": str(qty),
                    "rate_charged": "100.00",
                    "tax_rate": "18.00",
                }
            ],
            "place_of_supply": "29",
            "tax_mode": "exclusive",
        }
        res = client.post("/api/invoices/drafts/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return Invoice.objects.get(pk=res.data["id"])

    def _create_posted_invoice(self, invoice_number="POST-001"):
        draft = self._create_draft(self.admin, invoice_number=invoice_number, qty=2)
        res = self._client_for(self.admin).post(f"/api/invoices/{draft.pk}/post/", {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        draft.refresh_from_db()
        return draft

    def _create_cancelled_invoice(self, invoice_number="CANC-001"):
        posted = self._create_posted_invoice(invoice_number=invoice_number)
        return cancel_invoice(invoice_id=posted.pk, cancelled_by=self.admin, reason="Test cancellation")

    def test_a_admin_deletes_own_draft_success(self):
        draft = self._create_draft(self.admin, "DR-ADMIN-OWN")
        draft_id = draft.pk
        client = self._client_for(self.admin)

        res = client.delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get("detail"), "Draft invoice deleted successfully.")
        self.assertFalse(Invoice.objects.filter(pk=draft_id).exists())

    def test_b_admin_deletes_another_users_draft_success(self):
        draft = self._create_draft(self.staff1, "DR-STAFF-1")
        draft_id = draft.pk
        client = self._client_for(self.admin)

        res = client.delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Invoice.objects.filter(pk=draft_id).exists())

    def test_c_staff_deletes_own_draft_success(self):
        draft = self._create_draft(self.staff1, "DR-STAFF1-OWN")
        draft_id = draft.pk
        client = self._client_for(self.staff1)

        res = client.delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Invoice.objects.filter(pk=draft_id).exists())

    def test_d_staff_attempts_to_delete_another_users_draft_rejected(self):
        draft = self._create_draft(self.staff1, "DR-STAFF1-FOR-STAFF2")
        draft_id = draft.pk
        client = self._client_for(self.staff2)

        res = client.delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Invoice.objects.filter(pk=draft_id).exists())

    def test_e_staff_and_admin_cannot_delete_posted_invoice(self):
        posted = self._create_posted_invoice("POST-REJECT-DEL")
        posted_id = posted.pk

        # Admin attempt
        res_admin = self._client_for(self.admin).delete(f"/api/invoices/{posted_id}/draft/")
        self.assertEqual(res_admin.status_code, 400)
        self.assertIn("Only draft invoices can be deleted", str(res_admin.data))
        self.assertTrue(Invoice.objects.filter(pk=posted_id).exists())

        # Staff attempt
        res_staff = self._client_for(self.staff1).delete(f"/api/invoices/{posted_id}/draft/")
        self.assertEqual(res_staff.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=posted_id).exists())

    def test_f_staff_and_admin_cannot_delete_cancelled_invoice(self):
        cancelled = self._create_cancelled_invoice("CANC-REJECT-DEL")
        cancelled_id = cancelled.pk

        res_admin = self._client_for(self.admin).delete(f"/api/invoices/{cancelled_id}/draft/")
        self.assertEqual(res_admin.status_code, 400)
        self.assertIn("Only draft invoices can be deleted", str(res_admin.data))
        self.assertTrue(Invoice.objects.filter(pk=cancelled_id).exists())

        res_staff = self._client_for(self.staff1).delete(f"/api/invoices/{cancelled_id}/draft/")
        self.assertEqual(res_staff.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=cancelled_id).exists())

    def test_g_unauthorized_user_cannot_delete_draft(self):
        draft = self._create_draft(self.staff1, "DR-UNAUTH")
        draft_id = draft.pk

        unauth_client = self._client_for(None)
        res = unauth_client.delete(f"/api/invoices/{draft_id}/draft/")
        self.assertIn(res.status_code, [401, 403])
        self.assertTrue(Invoice.objects.filter(pk=draft_id).exists())

    def test_h_draft_line_items_are_removed_with_draft(self):
        draft = self._create_draft(self.admin, "DR-CASCADE-LINES")
        draft_id = draft.pk
        line_item_ids = list(draft.line_items.values_list("id", flat=True))
        self.assertGreater(len(line_item_ids), 0)

        res = self._client_for(self.admin).delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Invoice.objects.filter(pk=draft_id).exists())
        self.assertEqual(InvoiceLineItem.objects.filter(id__in=line_item_ids).count(), 0)

    def test_i_j_no_inventory_balance_or_stock_ledger_changes(self):
        self.product_balance.refresh_from_db()
        initial_stock = self.product_balance.quantity_on_hand
        initial_wac = self.product_balance.average_cost
        initial_ledger_count = StockLedger.objects.count()

        draft = self._create_draft(self.admin, "DR-NO-STOCK-EFFECT", qty=5)
        res = self._client_for(self.admin).delete(f"/api/invoices/{draft.pk}/draft/")
        self.assertEqual(res.status_code, 200)

        self.product_balance.refresh_from_db()
        self.assertEqual(self.product_balance.quantity_on_hand, initial_stock)
        self.assertEqual(self.product_balance.average_cost, initial_wac)
        self.assertEqual(StockLedger.objects.count(), initial_ledger_count)

    def test_k_no_customer_statement_or_financial_transaction_created(self):
        self.customer.refresh_from_db()
        initial_outstanding = self.customer.outstanding_balance
        initial_payments_count = Payment.objects.count()

        draft = self._create_draft(self.admin, "DR-NO-FIN-EFFECT", qty=4)
        res = self._client_for(self.admin).delete(f"/api/invoices/{draft.pk}/draft/")
        self.assertEqual(res.status_code, 200)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, initial_outstanding)
        self.assertEqual(Payment.objects.count(), initial_payments_count)

    def test_l_audit_log_is_created_for_successful_draft_deletion(self):
        draft = self._create_draft(self.staff1, "DR-AUDIT-TEST", qty=3)
        draft_id = draft.pk
        inv_number = draft.invoice_number
        customer_id = draft.customer_id
        total_amount = str(draft.total_amount)

        res = self._client_for(self.staff1).delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 200)

        audit = AuditLog.objects.filter(
            action="DRAFT_INVOICE_DELETED",
            entity_type="Invoice",
            entity_id=draft_id,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user_id, self.staff1.pk)
        self.assertEqual(audit.metadata.get("invoice_number"), inv_number)
        self.assertEqual(audit.metadata.get("customer_id"), customer_id)
        self.assertEqual(audit.metadata.get("total_amount"), total_amount)
        self.assertEqual(audit.metadata.get("state"), "DRAFT")
        self.assertEqual(audit.metadata.get("line_items_count"), 1)

    def test_m_failed_deletion_attempts_do_not_alter_data(self):
        draft = self._create_draft(self.staff1, "DR-FAILED-ATTEMPT", qty=2)
        draft_id = draft.pk
        initial_audit_count = AuditLog.objects.filter(action="DRAFT_INVOICE_DELETED").count()

        # Unauthorized staff attempt
        res = self._client_for(self.staff2).delete(f"/api/invoices/{draft_id}/draft/")
        self.assertEqual(res.status_code, 403)

        # Confirm draft still exists with line items
        draft.refresh_from_db()
        self.assertEqual(draft.state, Invoice.STATE_DRAFT)
        self.assertEqual(draft.line_items.count(), 1)
        # Confirm no deletion audit log created on failure
        self.assertEqual(AuditLog.objects.filter(action="DRAFT_INVOICE_DELETED").count(), initial_audit_count)
