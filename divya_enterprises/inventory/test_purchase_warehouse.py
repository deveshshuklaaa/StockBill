"""Purchases cannot be received into a non-sellable (Damaged / Quarantine) warehouse."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile
from inventory.models import InventoryBalance, Product, PurchaseInvoice, Supplier, TaxRate, Warehouse
from inventory.purchase_services import create_purchase, post_purchase, update_purchase
from inventory.services import get_damaged_warehouse, get_default_warehouse

User = get_user_model()


class PurchaseWarehouseTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="pw_admin", password="StrongPass123!", role="admin")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        BusinessProfile.objects.create(business_name="B", gstin="29X", registered_address="A", state="K", state_code="29")
        self.supplier = Supplier.objects.create(name="Supplier", state_code="29")
        tax = TaxRate.objects.create(name="Nil", rate=Decimal("0.00"))
        self.product = Product.objects.create(name="Chips", tax=tax)
        self.main = get_default_warehouse()
        self.damaged = get_damaged_warehouse()
        self.lines = [{"product": self.product, "quantity": "10", "rate": "5.00", "tax_rate": "0.00"}]

    def payload(self, warehouse):
        return {
            "supplier": self.supplier.pk,
            "warehouse": warehouse.pk,
            "invoice_date": "2026-11-27",
            "tax_mode": "exclusive",
            "line_items": [{"product": self.product.pk, "quantity": "10", "rate": "5.00"}],
        }

    def test_api_rejects_a_purchase_into_damaged(self):
        response = self.client.post("/api/purchase-invoices/", self.payload(self.damaged), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("warehouse", response.data)
        self.assertFalse(PurchaseInvoice.objects.exists())

    def test_posting_a_purchase_into_damaged_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_purchase(
                supplier=self.supplier, warehouse=self.damaged, invoice_date=date.today(),
                line_items=self.lines, created_by=self.admin, post=True,
            )
        self.assertFalse(PurchaseInvoice.objects.exists())
        self.assertFalse(InventoryBalance.objects.filter(warehouse=self.damaged).exists())

    def test_a_draft_cannot_be_moved_into_damaged(self):
        draft = create_purchase(
            supplier=self.supplier, warehouse=self.main, invoice_date=date.today(),
            line_items=self.lines, created_by=self.admin,
        )
        with self.assertRaises(ValidationError):
            update_purchase(purchase_id=draft.pk, updated_by=self.admin, warehouse=self.damaged)
        draft.refresh_from_db()
        self.assertEqual(draft.warehouse_id, self.main.pk)

    def test_an_older_draft_in_damaged_cannot_be_posted(self):
        draft = create_purchase(
            supplier=self.supplier, warehouse=self.main, invoice_date=date.today(),
            line_items=self.lines, created_by=self.admin,
        )
        # A draft saved before the rule existed.
        PurchaseInvoice.objects.filter(pk=draft.pk).update(warehouse=self.damaged)
        response = self.client.post(f"/api/purchase-invoices/{draft.pk}/post/")
        self.assertEqual(response.status_code, 400)
        draft.refresh_from_db()
        self.assertEqual(draft.state, PurchaseInvoice.STATE_DRAFT)
        self.assertFalse(InventoryBalance.objects.filter(warehouse=self.damaged).exists())

    def test_sellable_warehouses_still_receive(self):
        van = Warehouse.objects.create(name="Van 1", code="VAN1")
        for warehouse in (self.main, van):
            response = self.client.post("/api/purchase-invoices/", self.payload(warehouse), format="json")
            self.assertEqual(response.status_code, 201, response.data)
            posted = self.client.post(f"/api/purchase-invoices/{response.data['id']}/post/")
            self.assertEqual(posted.status_code, 200, posted.data)
            self.assertEqual(
                InventoryBalance.objects.get(product=self.product, warehouse=warehouse).quantity_on_hand,
                Decimal("10.000"),
            )
