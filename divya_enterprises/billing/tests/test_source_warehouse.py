"""Warehouse-aware invoicing: an invoice may draw stock from a chosen
warehouse; without one it behaves exactly as before (default Main)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice
from customers.models import Customer
from inventory.models import InventoryBalance, Product, StockLedger, TaxRate, Warehouse
from inventory.services import DEFAULT_WAREHOUSE_CODE, get_default_warehouse
from inventory.transfer_services import post_warehouse_transfer


class SourceWarehouseInvoiceTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="wh_invoice_admin", password="StrongPass123!", role="admin"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.customer = Customer.objects.create(
            name="Route Customer",
            contact_info="9999999999",
            customer_type=Customer.CUSTOMER_TYPE_B2C,
            state_code="29",
        )
        self.tax = TaxRate.objects.create(name="18%", rate=Decimal("18.00"))
        BusinessProfile.objects.create(
            business_name="Test Business",
            gstin="29TEST8888",
            registered_address="Addr",
            state="Karnataka",
            state_code="29",
        )
        # 100 pieces bootstrap into Main at cost 60 on first touch.
        self.product = Product.objects.create(
            name="Chips",
            default_price=100,
            cost_price=60,
            tax=self.tax,
            current_stock=100,
        )
        self.main = get_default_warehouse()
        self.van = Warehouse.objects.create(name="Van 1", code="VAN1")
        # Move 30 to the van (carries WAC 60 across).
        post_warehouse_transfer(
            product=self.product,
            source_warehouse=self.main,
            destination_warehouse=self.van,
            quantity=Decimal("30"),
            unit="piece",
            reason="Load van",
            effective_date=date.today(),
            created_by=self.user,
        )

    def qty(self, warehouse):
        return InventoryBalance.objects.get(product=self.product, warehouse=warehouse).quantity_on_hand

    def payload(self, quantity=5, **extra):
        data = {
            "customer": self.customer.pk,
            "payment_type": "credit",
            "place_of_supply": "29",
            "tax_mode": "exclusive",
            "line_items": [
                {"product": self.product.pk, "quantity": str(quantity), "rate_charged": "100.00", "tax_rate": "18.00"}
            ],
        }
        data.update(extra)
        return data

    def test_posted_invoice_with_explicit_source_deducts_from_that_warehouse(self):
        response = self.client.post("/api/invoices/", self.payload(5, source_warehouse=self.van.pk), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["source_warehouse"], self.van.pk)
        self.assertEqual(response.data["source_warehouse_code"], "VAN1")
        self.assertEqual(response.data["source_warehouse_name"], "Van 1")
        self.assertEqual(self.qty(self.van), Decimal("25.000"))
        self.assertEqual(self.qty(self.main), Decimal("70.000"))
        invoice = Invoice.objects.get(pk=response.data["id"])
        self.assertEqual(invoice.source_warehouse_id, self.van.pk)
        sale = StockLedger.objects.get(reference_type="invoice", reference_id=invoice.pk)
        self.assertEqual(sale.warehouse_id, self.van.pk)
        self.assertEqual(sale.quantity_delta, Decimal("-5.000"))
        # COGS snapshot comes from the source warehouse's WAC.
        self.assertEqual(invoice.line_items.get().cost_price_snapshot, Decimal("60.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("95.000"))

    def test_stock_is_checked_in_the_source_warehouse(self):
        response = self.client.post("/api/invoices/", self.payload(31, source_warehouse=self.van.pk), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient stock", str(response.data))
        self.assertEqual(self.qty(self.van), Decimal("30.000"))
        self.assertEqual(self.qty(self.main), Decimal("70.000"))
        self.assertFalse(Invoice.objects.exists())

    def test_cancelling_returns_stock_to_the_source_warehouse(self):
        response = self.client.post("/api/invoices/", self.payload(5, source_warehouse=self.van.pk), format="json")
        invoice_id = response.data["id"]
        cancel = self.client.post(f"/api/invoices/{invoice_id}/cancel/", {"reason": "Wrong route"}, format="json")
        self.assertEqual(cancel.status_code, 200, cancel.data)
        self.assertEqual(self.qty(self.van), Decimal("30.000"))
        self.assertEqual(self.qty(self.main), Decimal("70.000"))
        reversal = StockLedger.objects.get(reference_type="invoice_cancellation", reference_id=invoice_id)
        self.assertEqual(reversal.warehouse_id, self.van.pk)
        self.assertEqual(reversal.movement_type, StockLedger.SALE_REVERSAL)

    def test_omitting_source_behaves_as_default_main(self):
        response = self.client.post("/api/invoices/", self.payload(5), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["source_warehouse"])
        self.assertIsNone(response.data["source_warehouse_code"])
        self.assertIsNone(Invoice.objects.get(pk=response.data["id"]).source_warehouse_id)
        self.assertEqual(self.qty(self.main), Decimal("65.000"))
        self.assertEqual(self.qty(self.van), Decimal("30.000"))
        sale = StockLedger.objects.get(reference_type="invoice", reference_id=response.data["id"])
        self.assertEqual(sale.warehouse.code, DEFAULT_WAREHOUSE_CODE)
        self.client.post(f"/api/invoices/{response.data['id']}/cancel/", {"reason": "x"}, format="json")
        self.assertEqual(self.qty(self.main), Decimal("70.000"))

    def test_explicit_null_source_is_main(self):
        response = self.client.post("/api/invoices/", self.payload(5, source_warehouse=None), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.qty(self.main), Decimal("65.000"))

    def test_draft_keeps_source_and_posting_deducts_from_it(self):
        draft = self.client.post("/api/invoices/drafts/", self.payload(4, source_warehouse=self.van.pk), format="json")
        self.assertEqual(draft.status_code, 201, draft.data)
        self.assertEqual(draft.data["state"], "DRAFT")
        self.assertEqual(draft.data["source_warehouse"], self.van.pk)
        self.assertEqual(self.qty(self.van), Decimal("30.000"))
        posted = self.client.post(f"/api/invoices/{draft.data['id']}/post/")
        self.assertEqual(posted.status_code, 200, posted.data)
        self.assertEqual(self.qty(self.van), Decimal("26.000"))
        self.assertEqual(self.qty(self.main), Decimal("70.000"))

    def test_draft_update_keeps_source_when_absent_and_resets_on_null(self):
        draft = self.client.post("/api/invoices/drafts/", self.payload(4, source_warehouse=self.van.pk), format="json")
        draft_id = draft.data["id"]
        kept = self.client.patch(f"/api/invoices/{draft_id}/draft/", self.payload(6), format="json")
        self.assertEqual(kept.status_code, 200, kept.data)
        self.assertEqual(kept.data["source_warehouse"], self.van.pk)
        reset = self.client.patch(f"/api/invoices/{draft_id}/draft/", self.payload(6, source_warehouse=None), format="json")
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertIsNone(reset.data["source_warehouse"])
        moved = self.client.patch(f"/api/invoices/{draft_id}/draft/", self.payload(6, source_warehouse=self.van.pk), format="json")
        self.assertEqual(moved.data["source_warehouse"], self.van.pk)
        self.client.post(f"/api/invoices/{draft_id}/post/")
        self.assertEqual(self.qty(self.van), Decimal("24.000"))

    def test_draft_update_rejects_unknown_warehouse(self):
        draft = self.client.post("/api/invoices/drafts/", self.payload(4), format="json")
        bad = self.client.patch(f"/api/invoices/{draft.data['id']}/draft/", self.payload(4, source_warehouse=999999), format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("source_warehouse", bad.data)

    def test_posting_a_draft_whose_warehouse_was_deactivated_is_rejected(self):
        draft = self.client.post("/api/invoices/drafts/", self.payload(4, source_warehouse=self.van.pk), format="json")
        Warehouse.objects.filter(pk=self.van.pk).update(is_active=False)
        posted = self.client.post(f"/api/invoices/{draft.data['id']}/post/")
        self.assertEqual(posted.status_code, 400)
        self.assertEqual(self.qty(self.van), Decimal("30.000"))
        self.assertEqual(Invoice.objects.get(pk=draft.data["id"]).state, Invoice.STATE_DRAFT)

    def test_inactive_warehouse_is_not_selectable(self):
        inactive = Warehouse.objects.create(name="Closed", code="CLOSED", is_active=False)
        response = self.client.post("/api/invoices/", self.payload(1, source_warehouse=inactive.pk), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("source_warehouse", response.data)

    def test_amendment_carries_the_source_warehouse(self):
        original = self.client.post("/api/invoices/", self.payload(5, source_warehouse=self.van.pk), format="json")
        amend_payload = self.payload(2)
        amend_payload["reason"] = "Wrong quantity"
        response = self.client.post(f"/api/invoices/{original.data['id']}/amend/", amend_payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["replacement"]["source_warehouse"], self.van.pk)
        # 30 - 5 (original) + 5 (cancel) - 2 (replacement)
        self.assertEqual(self.qty(self.van), Decimal("28.000"))
        self.assertEqual(self.qty(self.main), Decimal("70.000"))

    def test_source_warehouse_is_immutable_once_posted(self):
        response = self.client.post("/api/invoices/", self.payload(5, source_warehouse=self.van.pk), format="json")
        invoice = Invoice.objects.get(pk=response.data["id"])
        invoice.source_warehouse = self.main
        with self.assertRaises(ValueError):
            invoice.save()
