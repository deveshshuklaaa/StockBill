from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import AuditLog
from inventory.models import (
    InventoryBalance,
    Product,
    StockLedger,
    Warehouse,
)
from inventory.services import get_default_warehouse

User = get_user_model()


class WarehouseManagementTests(APITestCase):
    """Tests for Feature 1: Warehouse Management."""

    def setUp(self):
        super().setUp()
        self.default_warehouse = get_default_warehouse()

        self.admin = User.objects.create_user(
            username="wh_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="wh_staff", password="password", role=User.ROLE_STAFF
        )

    def test_list_warehouses_staff_and_admin(self):
        """Staff and Admin can both view warehouses."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/warehouses/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data.get("results", res.data)), 1)

    def test_create_warehouse_admin_success(self):
        """Admin can create a new warehouse with valid state details."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "name": "Bhiwandi Hub",
            "code": "BHI-01",
            "address": "Gala No 5, Bhiwandi",
            "state": "Maharashtra",
            "state_code": "27",
            "is_active": True,
        }
        res = self.client.post("/api/warehouses/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["code"], "BHI-01")
        self.assertEqual(res.data["state_code"], "27")
        self.assertTrue(Warehouse.objects.filter(code="BHI-01").exists())

    def test_create_warehouse_staff_forbidden(self):
        """Staff cannot create warehouses."""
        self.client.force_authenticate(user=self.staff)
        payload = {
            "name": "Staff Warehouse",
            "code": "STF-01",
            "state": "Maharashtra",
            "state_code": "27",
        }
        res = self.client.post("/api/warehouses/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_warehouse_duplicate_code_rejected(self):
        """Warehouse code must be unique."""
        self.client.force_authenticate(user=self.admin)
        Warehouse.objects.create(name="Warehouse A", code="DUP-01")
        payload = {
            "name": "Warehouse B",
            "code": "DUP-01",
            "state": "Maharashtra",
            "state_code": "27",
        }
        res = self.client.post("/api/warehouses/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("code", res.data)

    def test_create_warehouse_invalid_state_code(self):
        """State code must be 2 digits."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "name": "Invalid State WH",
            "code": "INV-01",
            "state": "Maharashtra",
            "state_code": "270",
        }
        res = self.client.post("/api/warehouses/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("state_code", res.data)

    def test_update_warehouse_admin(self):
        """Admin can edit warehouse details."""
        wh = Warehouse.objects.create(name="Old Name", code="UPD-01")
        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(
            f"/api/warehouses/{wh.id}/",
            {"name": "New Name", "address": "New Address"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        wh.refresh_from_db()
        self.assertEqual(wh.name, "New Name")
        self.assertEqual(wh.address, "New Address")

    def test_deactivate_and_filter_active_only(self):
        """Inactive warehouses can be filtered out."""
        wh = Warehouse.objects.create(name="Inactive WH", code="INA-01", is_active=False)
        self.client.force_authenticate(user=self.staff)

        # Query all
        res_all = self.client.get("/api/warehouses/")
        all_ids = [w["id"] for w in res_all.data.get("results", res_all.data)]
        self.assertIn(wh.id, all_ids)

        # Query active only
        res_active = self.client.get("/api/warehouses/?is_active=true")
        active_ids = [w["id"] for w in res_active.data.get("results", res_active.data)]
        self.assertNotIn(wh.id, active_ids)

    def test_delete_warehouse_without_dependencies_hard_deletes(self):
        """A warehouse with zero transactions/balances can be deleted."""
        wh = Warehouse.objects.create(name="Unused WH", code="DEL-01")
        self.client.force_authenticate(user=self.admin)
        res = self.client.delete(f"/api/warehouses/{wh.id}/")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Warehouse.objects.filter(id=wh.id).exists())

    def test_delete_warehouse_with_dependencies_deactivates_instead_of_hard_delete(self):
        """A warehouse with stock ledger history is deactivated rather than broken by hard delete."""
        wh = Warehouse.objects.create(name="Used WH", code="USD-01", is_active=True)
        prod = Product.objects.create(
            name="Test WH Prod", brand="Chheda", sku="WH-TEST-SKU", mrp=Decimal("10.00")
        )
        StockLedger.objects.create(
            warehouse=wh,
            product=prod,
            movement_type="PURCHASE",
            quantity_change=Decimal("10.000"),
            quantity_delta=Decimal("10.000"),
            unit_cost=Decimal("7.00"),
        )

        self.client.force_authenticate(user=self.admin)
        res = self.client.delete(f"/api/warehouses/{wh.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get("status"), "archived")

        wh.refresh_from_db()
        self.assertFalse(wh.is_active)
        self.assertTrue(Warehouse.objects.filter(id=wh.id).exists())
