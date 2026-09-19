import datetime
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import AuditLog, Invoice, InvoiceLineItem
from inventory.adjustment_services import post_stock_adjustment
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    PurchaseInvoice,
    PurchaseLineItem,
    StockAdjustment,
    StockAdjustmentNumberCounter,
    StockLedger,
    Warehouse,
)
from inventory.services import ensure_inventory_balance, get_default_warehouse

User = get_user_model()


class StockAdjustmentTests(APITestCase):
    """Comprehensive test suite for Phase 2 Stock Adjustments."""

    def setUp(self):
        super().setUp()
        self.warehouse = get_default_warehouse()

        # Users
        self.admin = User.objects.create_user(
            username="adj_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="adj_staff", password="password", role=User.ROLE_STAFF
        )

        # Attribute system for units_per_master_box
        self.category = Category.objects.create(code="SNK", name="Snacks Test")
        self.mb_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.get_or_create(
            category=self.category, attribute_definition=self.mb_attr
        )

        # Isolated test products
        self.product_192 = Product.objects.create(
            name="Test Chheda Snax 192",
            brand="Chheda",
            sku="TEST-SKU-192",
            mrp=Decimal("10.00"),
            cost_price=Decimal("6.00"),
            current_stock=Decimal("0.000"),
            catalogue_category=self.category,
        )
        ProductAttributeValue.objects.create(
            product=self.product_192,
            attribute_definition=self.mb_attr,
            value_integer=192,
        )

        self.product_120 = Product.objects.create(
            name="Test Chheda Masala 120",
            brand="Chheda",
            sku="TEST-SKU-120",
            mrp=Decimal("5.00"),
            cost_price=Decimal("3.00"),
            current_stock=Decimal("0.000"),
            catalogue_category=self.category,
        )
        ProductAttributeValue.objects.create(
            product=self.product_120,
            attribute_definition=self.mb_attr,
            value_integer=120,
        )

        self.product_252 = Product.objects.create(
            name="Test Chheda Wafers 252",
            brand="Chheda",
            sku="TEST-SKU-252",
            mrp=Decimal("10.00"),
            cost_price=Decimal("6.50"),
            current_stock=Decimal("0.000"),
            catalogue_category=self.category,
        )
        ProductAttributeValue.objects.create(
            product=self.product_252,
            attribute_definition=self.mb_attr,
            value_integer=252,
        )

        self.product_nobox = Product.objects.create(
            name="Test Single Item No Box",
            brand="Chheda",
            sku="TEST-SKU-NOBOX",
            mrp=Decimal("20.00"),
            cost_price=Decimal("15.00"),
            current_stock=Decimal("0.000"),
            catalogue_category=self.category,
        )

        self.client.force_authenticate(user=self.admin)

    # -------------------------------------------------------------------------
    # 1. Quantity & Units Tests
    # -------------------------------------------------------------------------

    def test_piece_in_adjustment(self):
        """Piece IN: 960 pieces -> +960 base pieces."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("960"),
            unit="piece",
            cost_per_piece=Decimal("6.66"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        self.assertEqual(adj.base_quantity, Decimal("960.000"))
        self.assertEqual(adj.adjustment_value, Decimal("6393.60"))
        self.product_192.refresh_from_db()
        self.assertEqual(self.product_192.current_stock, Decimal("960.000"))

        balance = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("960.000"))
        self.assertEqual(balance.average_cost, Decimal("6.66"))

        ledger = StockLedger.objects.filter(reference=adj.adjustment_number).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.movement_type, StockLedger.STOCK_ADJUSTMENT_IN)
        self.assertEqual(ledger.quantity_change, Decimal("960.000"))

    def test_master_box_in_adjustment(self):
        """Master Box IN: 5 boxes x 192 -> +960 base pieces."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("5"),
            unit="master box",
            cost_per_piece=Decimal("6.66"),
            reason="Physical Count Increase",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        self.assertEqual(adj.conversion_factor, Decimal("192.000"))
        self.assertEqual(adj.base_quantity, Decimal("960.000"))
        self.assertEqual(adj.adjustment_value, Decimal("6393.60"))

        self.product_192.refresh_from_db()
        self.assertEqual(self.product_192.current_stock, Decimal("960.000"))

    def test_piece_and_master_box_equivalence(self):
        """Identical quantity entered as pieces or boxes produces the same inventory & WAC."""
        # 1. Add 960 pcs
        adj1 = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("960"),
            unit="piece",
            cost_per_piece=Decimal("6.66"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        bal1 = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)

        # 2. On product_252, add 960 pcs via 960 pieces
        # On product_120, add 960 pcs via 8 boxes x 120 = 960 pcs
        adj2 = post_stock_adjustment(
            product=self.product_120,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("8"),
            unit="master box",
            cost_per_piece=Decimal("6.66"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        bal2 = InventoryBalance.objects.get(product=self.product_120, warehouse=self.warehouse)

        self.assertEqual(adj1.base_quantity, adj2.base_quantity)
        self.assertEqual(bal1.quantity_on_hand, bal2.quantity_on_hand)
        self.assertEqual(bal1.average_cost, bal2.average_cost)
        self.assertEqual(adj1.adjustment_value, adj2.adjustment_value)

    def test_pack_size_120_box(self):
        """12 master boxes x 120 pcs -> 1,440 base pieces."""
        adj = post_stock_adjustment(
            product=self.product_120,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("12"),
            unit="master box",
            cost_per_piece=Decimal("3.33"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        self.assertEqual(adj.base_quantity, Decimal("1440.000"))
        self.assertEqual(adj.adjustment_value, Decimal("4795.20"))

    def test_pack_size_252_box(self):
        """5 master boxes x 252 pcs -> 1,260 base pieces."""
        adj = post_stock_adjustment(
            product=self.product_252,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("5"),
            unit="master box",
            cost_per_piece=Decimal("6.50"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        self.assertEqual(adj.base_quantity, Decimal("1260.000"))
        self.assertEqual(adj.adjustment_value, Decimal("8190.00"))

    def test_product_without_master_box_rejected_for_box_unit(self):
        """Selecting master box on a product with no units_per_master_box is rejected."""
        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_nobox.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "5",
                "unit": "master box",
                "cost_per_piece": "15.00",
                "reason": "Found Stock",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("has no master box size", str(response.data))

    # -------------------------------------------------------------------------
    # 2. WAC Costing Tests
    # -------------------------------------------------------------------------

    def test_zero_stock_in_wac_initialization(self):
        """Zero stock + IN at ₹6.66 -> WAC becomes ₹6.66."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("100"),
            unit="piece",
            cost_per_piece=Decimal("6.66"),
            reason="Physical Count Increase",
            note="Opening correction after count",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        balance = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)
        self.assertEqual(balance.average_cost, Decimal("6.66"))

    def test_existing_stock_in_weighted_average_calculation(self):
        """Verify weighted average: existing 100 @ 6.00 + new 100 @ 8.00 -> 200 @ 7.00."""
        # Initial stock 100 @ 6.00
        post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("100"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        # Additional stock 100 @ 8.00
        post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("100"),
            unit="piece",
            cost_per_piece=Decimal("8.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        balance = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("200.000"))
        self.assertEqual(balance.average_cost, Decimal("7.00"))

    def test_out_adjustment_wac_remains_unchanged(self):
        """OUT adjustment reduces quantity but leaves WAC unchanged."""
        # Seed 1,000 pcs @ ₹6.50
        post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("1000"),
            unit="piece",
            cost_per_piece=Decimal("6.50"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        # OUT 100 pcs
        adj_out = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_OUT,
            quantity=Decimal("100"),
            unit="piece",
            reason="Damaged",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        balance = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("900.000"))
        self.assertEqual(balance.average_cost, Decimal("6.50"))
        self.assertEqual(adj_out.cost_per_base_unit_snapshot, Decimal("6.50"))
        self.assertEqual(adj_out.adjustment_value, Decimal("650.00"))

        ledger = StockLedger.objects.filter(reference=adj_out.adjustment_number).first()
        self.assertEqual(ledger.quantity_change, Decimal("-100.000"))
        self.assertEqual(ledger.unit_cost, Decimal("6.50"))

    def test_out_ignores_client_provided_cost(self):
        """Backend ignores any manipulated client cost for OUT and snapshots authoritative WAC."""
        # Seed 50 pcs @ ₹10.00
        post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("50"),
            unit="piece",
            cost_per_piece=Decimal("10.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_OUT",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "999.99",  # Tampered client cost
                "reason": "Expired",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(response.data["cost_per_base_unit_snapshot"])), Decimal("10.00"))
        self.assertEqual(Decimal(str(response.data["adjustment_value"])), Decimal("100.00"))

    # -------------------------------------------------------------------------
    # 3. Validation & Negative Stock Protections
    # -------------------------------------------------------------------------

    def test_negative_stock_protection_rejected(self):
        """OUT greater than available stock must be rejected atomically."""
        # Stock = 50 pieces
        post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("50"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        # Attempt to adjust OUT 60 pieces
        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_OUT",
                "quantity": "60",
                "unit": "piece",
                "reason": "Missing/Short",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Insufficient stock for this adjustment", str(response.data))

        # Verify nothing mutated
        balance = InventoryBalance.objects.get(product=self.product_192, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("50.000"))
        self.product_192.refresh_from_db()
        self.assertEqual(self.product_192.current_stock, Decimal("50.000"))

    def test_zero_and_negative_quantity_rejected(self):
        """Zero and negative quantities are rejected."""
        for qty in ["0", "-5"]:
            response = self.client.post(
                "/api/inventory/adjustments/",
                {
                    "product": self.product_192.id,
                    "warehouse": self.warehouse.id,
                    "adjustment_type": "STOCK_ADJUSTMENT_IN",
                    "quantity": qty,
                    "unit": "piece",
                    "cost_per_piece": "6.00",
                    "reason": "Found Stock",
                    "effective_date": str(datetime.date.today()),
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_future_effective_date_rejected(self):
        """Future effective dates must be rejected."""
        future = datetime.date.today() + datetime.timedelta(days=1)
        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "6.00",
                "reason": "Found Stock",
                "effective_date": str(future),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("effective_date", response.data)

    def test_reason_requirements_and_other_note(self):
        """Reason is mandatory; selecting 'Other' requires a note."""
        # Missing reason
        res1 = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "6.00",
                "reason": "",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(res1.status_code, status.HTTP_400_BAD_REQUEST)

        # Reason Other without note
        res2 = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "6.00",
                "reason": "Other",
                "note": "   ",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("note", str(res2.data))

        # Reason Other with note succeeds
        res3 = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "6.00",
                "reason": "Other",
                "note": "Floor audit recount difference",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(res3.status_code, status.HTTP_201_CREATED)

    def test_in_without_cost_rejected(self):
        """STOCK_ADJUSTMENT_IN without cost_per_piece is rejected."""
        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "reason": "Found Stock",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cost_per_piece", response.data)

    # -------------------------------------------------------------------------
    # 4. Security & Permissions Tests
    # -------------------------------------------------------------------------

    def test_staff_cannot_create_adjustment(self):
        """Staff user must be forbidden from creating adjustments (403)."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(
            "/api/inventory/adjustments/",
            {
                "product": self.product_192.id,
                "warehouse": self.warehouse.id,
                "adjustment_type": "STOCK_ADJUSTMENT_IN",
                "quantity": "10",
                "unit": "piece",
                "cost_per_piece": "6.00",
                "reason": "Found Stock",
                "effective_date": str(datetime.date.today()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_view_adjustments_and_details(self):
        """Staff user can view the list and details of adjustments."""
        # Create an adjustment as admin
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("10"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        self.client.force_authenticate(user=self.staff)
        list_res = self.client.get("/api/inventory/adjustments/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_res.data["results"]), 1)

        detail_res = self.client.get(f"/api/inventory/adjustments/{adj.id}/")
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data["adjustment_number"], adj.adjustment_number)

    # -------------------------------------------------------------------------
    # 5. Immutability & Model Protection Tests
    # -------------------------------------------------------------------------

    def test_adjustment_cannot_be_modified_or_deleted(self):
        """StockAdjustment is append-only: save() on existing instance or delete() raises ValueError."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("10"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        with self.assertRaises(ValueError):
            adj.reason = "Modified Reason"
            adj.save()

        with self.assertRaises(ValueError):
            adj.delete()

    def test_api_put_patch_delete_disallowed(self):
        """HTTP PUT, PATCH, DELETE are rejected on the detail endpoint with 405 Method Not Allowed."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("10"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        put_res = self.client.put(f"/api/inventory/adjustments/{adj.id}/", {"reason": "changed"})
        self.assertEqual(put_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        patch_res = self.client.patch(f"/api/inventory/adjustments/{adj.id}/", {"reason": "changed"})
        self.assertEqual(patch_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        del_res = self.client.delete(f"/api/inventory/adjustments/{adj.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # -------------------------------------------------------------------------
    # 6. Idempotency & Concurrency Tests
    # -------------------------------------------------------------------------

    def test_idempotency_key_replay(self):
        """Replaying identical request with the same Idempotency-Key returns original object without duplicate movement."""
        headers = {"HTTP_IDEMPOTENCY_KEY": "test-key-adj-001"}
        payload = {
            "product": self.product_192.id,
            "warehouse": self.warehouse.id,
            "adjustment_type": "STOCK_ADJUSTMENT_IN",
            "quantity": "50",
            "unit": "piece",
            "cost_per_piece": "6.00",
            "reason": "Found Stock",
            "effective_date": str(datetime.date.today()),
        }

        res1 = self.client.post("/api/inventory/adjustments/", payload, **headers)
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        adj_num = res1.data["adjustment_number"]

        # Second request with same idempotency key
        res2 = self.client.post("/api/inventory/adjustments/", payload, **headers)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["adjustment_number"], adj_num)

        # Confirm exactly 1 adjustment and 1 stock ledger record exists for this product
        self.assertEqual(
            StockAdjustment.objects.filter(product=self.product_192).count(), 1
        )
        self.assertEqual(
            StockLedger.objects.filter(product=self.product_192).count(), 1
        )

    def test_idempotency_key_conflict_with_different_payload(self):
        """Replaying the same Idempotency-Key with different payload returns 409 Conflict."""
        headers = {"HTTP_IDEMPOTENCY_KEY": "test-key-conflict-002"}
        payload1 = {
            "product": self.product_192.id,
            "warehouse": self.warehouse.id,
            "adjustment_type": "STOCK_ADJUSTMENT_IN",
            "quantity": "50",
            "unit": "piece",
            "cost_per_piece": "6.00",
            "reason": "Found Stock",
            "effective_date": str(datetime.date.today()),
        }
        res1 = self.client.post("/api/inventory/adjustments/", payload1, **headers)
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        payload2 = dict(payload1)
        payload2["quantity"] = "100"  # altered payload
        res2 = self.client.post("/api/inventory/adjustments/", payload2, **headers)
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)

    # -------------------------------------------------------------------------
    # 7. Atomicity & Gapless Numbering Rollback
    # -------------------------------------------------------------------------

    def test_atomicity_and_gapless_counter_rollback(self):
        """If transaction fails, counter serial is not consumed and no partial record is kept."""
        fy_code = "26-27"
        counter, _ = StockAdjustmentNumberCounter.objects.get_or_create(fy_code=fy_code)
        initial_serial = counter.last_serial

        # Trigger an intentional error inside transaction after number peek
        with self.assertRaises(ZeroDivisionError):
            with transaction.atomic():
                # allocate number
                from inventory.adjustment_numbering import next_adjustment_number
                next_adjustment_number(datetime.date(2026, 9, 1))
                # raise error to rollback
                1 / 0

        counter.refresh_from_db()
        self.assertEqual(counter.last_serial, initial_serial)

    # -------------------------------------------------------------------------
    # 8. Audit Logging & Search/Filters
    # -------------------------------------------------------------------------

    def test_audit_log_created_for_adjustment(self):
        """Every successfully posted adjustment creates a detailed AuditLog."""
        adj = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("20"),
            unit="piece",
            cost_per_piece=Decimal("6.50"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        audit = AuditLog.objects.filter(
            entity_type="StockAdjustment", entity_id=adj.id
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.action, "stock_adjustment_created")
        self.assertEqual(audit.metadata["direction"], "STOCK_ADJUSTMENT_IN")
        self.assertEqual(audit.metadata["product_name"], self.product_192.name)

    def test_list_filters(self):
        """Test filtering adjustments by type, product, warehouse, reason, and search."""
        adj_in = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_IN,
            quantity=Decimal("100"),
            unit="piece",
            cost_per_piece=Decimal("6.00"),
            reason="Found Stock",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )
        adj_out = post_stock_adjustment(
            product=self.product_192,
            warehouse=self.warehouse,
            adjustment_type=StockAdjustment.ADJUSTMENT_TYPE_OUT,
            quantity=Decimal("10"),
            unit="piece",
            reason="Damaged",
            note="Water leak near rack",
            effective_date=datetime.date.today(),
            created_by=self.admin,
        )

        # Filter by type=STOCK_ADJUSTMENT_OUT
        r_type = self.client.get("/api/inventory/adjustments/", {"type": "STOCK_ADJUSTMENT_OUT"})
        self.assertEqual(r_type.status_code, status.HTTP_200_OK)
        numbers = [item["adjustment_number"] for item in r_type.data["results"]]
        self.assertIn(adj_out.adjustment_number, numbers)
        self.assertNotIn(adj_in.adjustment_number, numbers)

        # Filter by search note
        r_search = self.client.get("/api/inventory/adjustments/", {"search": "leak"})
        self.assertEqual(r_search.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r_search.data["results"]), 1)
        self.assertEqual(r_search.data["results"][0]["adjustment_number"], adj_out.adjustment_number)
