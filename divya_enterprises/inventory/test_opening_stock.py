import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import AuditLog
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    OpeningStock,
    Product,
    ProductAttributeValue,
    StockLedger,
    Warehouse,
)
from inventory.services import get_default_warehouse

User = get_user_model()


class OpeningStockTests(APITestCase):
    """Comprehensive test suite for Feature 2: Opening Stock."""

    def setUp(self):
        super().setUp()
        self.warehouse = get_default_warehouse()

        self.admin = User.objects.create_user(
            username="os_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="os_staff", password="password", role=User.ROLE_STAFF
        )

        # Attribute system for units_per_master_box
        self.category = Category.objects.create(code="SNK_OS", name="Snacks OS Test")
        self.mb_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.get_or_create(
            category=self.category, attribute_definition=self.mb_attr
        )

        # Products with pack sizes: 192, 120, 252
        self.prod_192 = Product.objects.create(
            name="Chheda Mix 192", brand="Chheda", sku="OS-192", catalogue_category=self.category, mrp=Decimal("10.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_192, attribute_definition=self.mb_attr, value_integer=192
        )

        self.prod_120 = Product.objects.create(
            name="Chheda Poha 120", brand="Chheda", sku="OS-120", catalogue_category=self.category, mrp=Decimal("10.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_120, attribute_definition=self.mb_attr, value_integer=120
        )

        self.prod_252 = Product.objects.create(
            name="Chheda Wafers 252", brand="Chheda", sku="OS-252", catalogue_category=self.category, mrp=Decimal("5.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_252, attribute_definition=self.mb_attr, value_integer=252
        )

        self.prod_piece = Product.objects.create(
            name="Standalone Item", brand="General", sku="OS-PC", mrp=Decimal("25.00")
        )

    def test_piece_input_success(self):
        """Piece unit input creates opening stock, inventory balance, and stock ledger entry."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_piece.id,
            "warehouse": self.warehouse.id,
            "unit": "piece",
            "quantity": 100,
            "cost_per_piece": "15.50",
            "effective_date": str(timezone.localdate()),
            "reason": "Inventory Initialization",
            "note": "Initial count",
        }
        res = self.client.post("/api/inventory/opening-stock/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("100.000"))
        self.assertEqual(Decimal(res.data["cost_per_piece"]), Decimal("15.50"))
        self.assertEqual(Decimal(res.data["opening_value"]), Decimal("1550.00"))
        self.assertTrue(res.data["opening_stock_number"].startswith("OS/"))

        # Verify InventoryBalance
        bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.warehouse)
        self.assertEqual(bal.quantity_on_hand, Decimal("100.000"))
        self.assertEqual(bal.average_cost, Decimal("15.50"))

        # Verify StockLedger
        ledger = StockLedger.objects.get(product=self.prod_piece, warehouse=self.warehouse)
        self.assertEqual(ledger.movement_type, "OPENING_STOCK")
        self.assertEqual(ledger.quantity_delta, Decimal("100.000"))
        self.assertEqual(ledger.unit_cost, Decimal("15.50"))

        # Verify AuditLog
        self.assertTrue(
            AuditLog.objects.filter(action="opening_stock_created", entity_id=res.data["id"]).exists()
        )

    def test_master_box_conversions(self):
        """Opening stock supports Master Box conversions for 192, 120, and 252 packs."""
        self.client.force_authenticate(user=self.admin)

        # 192 pack: 5 boxes * 192 = 960 pieces @ 7.10 = 6816.00
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_192.id,
                "warehouse": self.warehouse.id,
                "unit": "master box",
                "quantity": 5,
                "cost_per_piece": "7.10",
                "effective_date": str(timezone.localdate()),
                "reason": "Pre-existing Stock",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("960.000"))
        self.assertEqual(Decimal(res.data["opening_value"]), Decimal("6816.00"))

        # 120 pack: 10 boxes * 120 = 1200 pieces @ 8.00 = 9600.00
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_120.id,
                "warehouse": self.warehouse.id,
                "unit": "master box",
                "quantity": 10,
                "cost_per_piece": "8.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Pre-existing Stock",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("1200.000"))
        self.assertEqual(Decimal(res.data["opening_value"]), Decimal("9600.00"))

        # 252 pack: 4 boxes * 252 = 1008 pieces @ 3.50 = 3528.00
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_252.id,
                "warehouse": self.warehouse.id,
                "unit": "master box",
                "quantity": 4,
                "cost_per_piece": "3.50",
                "effective_date": str(timezone.localdate()),
                "reason": "Pre-existing Stock",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("1008.000"))
        self.assertEqual(Decimal(res.data["opening_value"]), Decimal("3528.00"))

    def test_duplicate_opening_stock_rejected(self):
        """A second opening stock for the same product and warehouse is rejected."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_piece.id,
            "warehouse": self.warehouse.id,
            "unit": "piece",
            "quantity": 50,
            "cost_per_piece": "10.00",
            "effective_date": str(timezone.localdate()),
            "reason": "Inventory Initialization",
        }
        res1 = self.client.post("/api/inventory/opening-stock/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        res2 = self.client.post("/api/inventory/opening-stock/", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already initialized", str(res2.data))

    def test_existing_stock_activity_rejected(self):
        """Opening stock is rejected if the product already has transactions/movements in that warehouse."""
        StockLedger.objects.create(
            warehouse=self.warehouse,
            product=self.prod_piece,
            movement_type="PURCHASE",
            quantity_change=Decimal("10.000"),
            quantity_delta=Decimal("10.000"),
            unit_cost=Decimal("15.00"),
        )

        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_piece.id,
            "warehouse": self.warehouse.id,
            "unit": "piece",
            "quantity": 50,
            "cost_per_piece": "10.00",
            "effective_date": str(timezone.localdate()),
            "reason": "Inventory Initialization",
        }
        res = self.client.post("/api/inventory/opening-stock/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already has stock ledger movements", str(res.data))

    def test_future_date_rejected(self):
        """Opening stock cannot have an effective date in the future."""
        self.client.force_authenticate(user=self.admin)
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        payload = {
            "product": self.prod_piece.id,
            "warehouse": self.warehouse.id,
            "unit": "piece",
            "quantity": 50,
            "cost_per_piece": "10.00",
            "effective_date": str(tomorrow),
            "reason": "Inventory Initialization",
        }
        res = self.client.post("/api/inventory/opening-stock/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("effective_date", str(res.data))

    def test_reason_validation(self):
        """Reason is required, and 'Other' requires an explanatory note."""
        self.client.force_authenticate(user=self.admin)

        # Missing reason
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": self.warehouse.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 'Other' without note
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": self.warehouse.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Other",
                "note": "",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("note", str(res.data))

        # 'Other' with note is accepted
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": self.warehouse.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Other",
                "note": "Audited physical count on takeover",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_inactive_warehouse_rejected(self):
        """Cannot create opening stock for an inactive warehouse."""
        wh = Warehouse.objects.create(name="Inactive WH", code="INA-OS", is_active=False)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": wh.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Inventory Initialization",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inactive warehouse", str(res.data).lower())

    def test_permissions(self):
        """Admin can create; staff cannot create but can read."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": self.warehouse.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Inventory Initialization",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Staff can list
        res_list = self.client.get("/api/inventory/opening-stock/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)

    def test_immutability(self):
        """Opening stock records cannot be edited or deleted."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/opening-stock/",
            {
                "product": self.prod_piece.id,
                "warehouse": self.warehouse.id,
                "unit": "piece",
                "quantity": 10,
                "cost_per_piece": "10.00",
                "effective_date": str(timezone.localdate()),
                "reason": "Inventory Initialization",
            },
            format="json",
        )
        os_id = res.data["id"]

        # Attempt PATCH
        patch_res = self.client.patch(
            f"/api/inventory/opening-stock/{os_id}/",
            {"quantity": 20},
            format="json",
        )
        self.assertEqual(patch_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Attempt DELETE
        del_res = self.client.delete(f"/api/inventory/opening-stock/{os_id}/")
        self.assertEqual(del_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_preview_endpoint(self):
        """Preview returns calculated quantities and cost without writing to DB."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/opening-stock/preview/",
            {
                "product": self.prod_192.id,
                "warehouse": self.warehouse.id,
                "unit": "master box",
                "quantity": 3,
                "cost_per_piece": "6.50",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("576.000"))
        self.assertEqual(Decimal(res.data["opening_value"]), Decimal("3744.00"))
        # Verify no opening stock record was created
        self.assertEqual(OpeningStock.objects.count(), 0)
