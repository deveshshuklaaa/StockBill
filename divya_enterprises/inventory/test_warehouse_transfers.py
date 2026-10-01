"""Comprehensive test suite for Feature 1: Warehouse Transfers.

Covers all 27 required cases:
1. Piece transfer
2. Master Box transfer
3. Conversion 192
4. Conversion 120
5. Conversion 252
6. Source stock decreases correctly
7. Destination stock increases correctly
8. Source WAC unchanged
9. Destination WAC when zero stock
10. Destination WAC when existing stock
11. Transfer value
12. Cannot transfer more than source stock
13. Cannot transfer zero/negative quantity
14. Source != destination
15. Inactive source rejected
16. Inactive destination rejected
17. Future date rejected
18. reason required
19. Other requires note
20. permissions
21. immutability
22. atomic rollback
23. idempotency
24. two ledger entries
25. correct movement types
26. audit log
27. total inventory valuation consistency
"""

import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import AuditLog
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    StockLedger,
    Warehouse,
    WarehouseTransfer,
    WarehouseTransferIdempotencyKey,
)
from inventory.services import ensure_inventory_balance, get_default_warehouse

User = get_user_model()


class WarehouseTransferTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username="trf_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="trf_staff", password="password", role=User.ROLE_STAFF
        )

        self.wh_source = Warehouse.objects.create(
            name="Main Hub", code="HUB-MAIN", is_active=True
        )
        self.wh_dest = Warehouse.objects.create(
            name="Branch Store", code="STORE-BR", is_active=True
        )
        self.wh_inactive = Warehouse.objects.create(
            name="Closed Depot", code="DEPOT-CL", is_active=False
        )

        # Attribute system for units_per_master_box
        self.category = Category.objects.create(code="SNK_TRF", name="Snacks Transfer Test")
        self.mb_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.get_or_create(
            category=self.category, attribute_definition=self.mb_attr
        )

        # Products with pack sizes: 192, 120, 252, and standalone piece
        self.prod_192 = Product.objects.create(
            name="Chheda Mix 192", brand="Chheda", sku="TRF-192", catalogue_category=self.category, mrp=Decimal("10.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_192, attribute_definition=self.mb_attr, value_integer=192
        )

        self.prod_120 = Product.objects.create(
            name="Chheda Poha 120", brand="Chheda", sku="TRF-120", catalogue_category=self.category, mrp=Decimal("10.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_120, attribute_definition=self.mb_attr, value_integer=120
        )

        self.prod_252 = Product.objects.create(
            name="Chheda Wafers 252", brand="Chheda", sku="TRF-252", catalogue_category=self.category, mrp=Decimal("5.00")
        )
        ProductAttributeValue.objects.create(
            product=self.prod_252, attribute_definition=self.mb_attr, value_integer=252
        )

        self.prod_piece = Product.objects.create(
            name="Piece Only Biscuit", brand="Parle", sku="TRF-PC", mrp=Decimal("25.00")
        )

    def _set_stock(self, product, warehouse, quantity, average_cost):
        """Helper to initialize warehouse inventory balance directly."""
        ensure_inventory_balance(product=product, warehouse=warehouse, created_by=self.admin)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL stockbill.allow_inventory_mutation = 'on'")
        balance = InventoryBalance.objects.get(product=product, warehouse=warehouse)
        balance._allow_service_update = True
        balance.quantity_on_hand = Decimal(str(quantity))
        balance.average_cost = Decimal(str(average_cost))
        balance.save()

        # Update product cached stock
        from django.db.models import Sum
        product._allow_stock_cache_update = True
        tot = InventoryBalance.objects.filter(product=product).aggregate(t=Sum("quantity_on_hand"))["t"] or Decimal("0.000")
        product.current_stock = tot
        product.save()

    def test_1_piece_transfer(self):
        """1. Piece transfer moves stock accurately."""
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "12.50")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_piece.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "25.000",
            "unit": "piece",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }
        res = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("25.000"))
        self.assertEqual(Decimal(res.data["unit_cost_snapshot"]), Decimal("12.50"))
        self.assertEqual(Decimal(res.data["transfer_value"]), Decimal("312.50"))

    def test_2_master_box_transfer(self):
        """2. Master Box transfer converts using units_per_master_box."""
        self._set_stock(self.prod_192, self.wh_source, "500.000", "6.20")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_192.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "2.000",
            "unit": "master box",
            "reason": WarehouseTransfer.REASON_INTER_BRANCH,
            "effective_date": timezone.localdate().isoformat(),
        }
        res = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # 2 boxes * 192 = 384 pcs
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("384.000"))
        self.assertEqual(Decimal(res.data["conversion_factor"]), Decimal("192.000"))
        self.assertEqual(Decimal(res.data["transfer_value"]), Decimal("2380.80"))

    def test_3_conversion_192(self):
        """3. Conversion 192 behaves correctly."""
        self._set_stock(self.prod_192, self.wh_source, "1000.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_192.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "1.000",
            "unit": "master box",
            "conversion_factor": "192.000",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }
        res = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("192.000"))

    def test_4_conversion_120(self):
        """4. Conversion 120 behaves correctly."""
        self._set_stock(self.prod_120, self.wh_source, "500.000", "7.00")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_120.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "3.000",
            "unit": "master box",
            "conversion_factor": "120.000",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }
        res = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # 3 * 120 = 360 pcs
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("360.000"))

    def test_5_conversion_252(self):
        """5. Conversion 252 behaves correctly."""
        self._set_stock(self.prod_252, self.wh_source, "1000.000", "3.50")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_252.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "2.000",
            "unit": "master box",
            "conversion_factor": "252.000",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }
        res = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # 2 * 252 = 504 pcs
        self.assertEqual(Decimal(res.data["base_quantity"]), Decimal("504.000"))

    def test_6_source_stock_decreases_correctly(self):
        """6. Source stock decreases by base quantity."""
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "10.00")
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "30.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_ORDER_FULFILLMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        src_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_source)
        self.assertEqual(src_bal.quantity_on_hand, Decimal("70.000"))

    def test_7_destination_stock_increases_correctly(self):
        """7. Destination stock increases by base quantity."""
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "10.00")
        self._set_stock(self.prod_piece, self.wh_dest, "15.000", "10.00")
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "20.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        dst_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_dest)
        self.assertEqual(dst_bal.quantity_on_hand, Decimal("35.000"))

    def test_8_source_wac_unchanged(self):
        """8. Source warehouse WAC remains untouched after transfer."""
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "5.20")
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "40.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        src_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_source)
        self.assertEqual(src_bal.average_cost, Decimal("5.20"))

    def test_9_destination_wac_when_zero_stock(self):
        """9. When destination has 0 stock, destination WAC becomes transferred unit cost."""
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "8.40")
        # wh_dest has 0 stock
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "30.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        dst_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_dest)
        self.assertEqual(dst_bal.average_cost, Decimal("8.40"))

    def test_10_destination_wac_when_existing_stock(self):
        """10. When destination has stock, WAC is recalculated with weighted average formula."""
        # Destination: 20 pcs @ 10.00 = 200.00
        # Source: 100 pcs @ 16.00
        # Transfer: 10 pcs @ 16.00 = 160.00
        # Destination resulting: 30 pcs, total val = 360.00 => WAC = 360 / 30 = 12.00
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "16.00")
        self._set_stock(self.prod_piece, self.wh_dest, "20.000", "10.00")
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "10.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        dst_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_dest)
        self.assertEqual(dst_bal.average_cost, Decimal("12.00"))
        self.assertEqual(dst_bal.quantity_on_hand, Decimal("30.000"))

    def test_11_transfer_value(self):
        """11. Transfer value equals transferred base quantity * source unit cost snapshot."""
        self._set_stock(self.prod_piece, self.wh_source, "80.000", "14.25")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "12.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REBALANCING,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        # 12 * 14.25 = 171.00
        self.assertEqual(Decimal(res.data["transfer_value"]), Decimal("171.00"))

    def test_12_cannot_transfer_more_than_source_stock(self):
        """12. Cannot transfer more stock than available in source warehouse."""
        self._set_stock(self.prod_piece, self.wh_source, "10.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "10.001",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Insufficient stock", str(res.data))

    def test_13_cannot_transfer_zero_or_negative_quantity(self):
        """13. Zero or negative quantity is rejected with 400."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        for bad_qty in ["0", "0.000", "-5"]:
            res = self.client.post(
                "/api/inventory/transfers/",
                {
                    "product": self.prod_piece.id,
                    "source_warehouse": self.wh_source.id,
                    "destination_warehouse": self.wh_dest.id,
                    "quantity": bad_qty,
                    "unit": "piece",
                    "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                    "effective_date": timezone.localdate().isoformat(),
                },
                format="json",
            )
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_14_source_must_not_equal_destination(self):
        """14. Source and destination warehouses must be different."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_source.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must be different", str(res.data))

    def test_15_inactive_source_rejected(self):
        """15. Inactive source warehouse is rejected."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_inactive.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_16_inactive_destination_rejected(self):
        """16. Inactive destination warehouse is rejected."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_inactive.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_17_future_date_rejected(self):
        """17. Future effective date is rejected."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        future_dt = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": future_dt,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("future", str(res.data).lower())

    def test_18_reason_required(self):
        """18. Reason is required."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": "",
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_19_other_requires_note(self):
        """19. Reason 'Other' requires a note."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_OTHER,
                "note": "",
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("note", str(res.data).lower())

    def test_20_permissions(self):
        """20. Admin can create, Staff is read-only, Anonymous is rejected."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        payload = {
            "product": self.prod_piece.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "5.000",
            "unit": "piece",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }

        # Anonymous
        self.client.force_authenticate(user=None)
        res_anon = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertIn(res_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # Staff can list
        self.client.force_authenticate(user=self.staff)
        res_list = self.client.get("/api/inventory/transfers/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)

        # Staff cannot create (403 Forbidden)
        res_staff_create = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res_staff_create.status_code, status.HTTP_403_FORBIDDEN)

        # Admin can create
        self.client.force_authenticate(user=self.admin)
        res_admin = self.client.post("/api/inventory/transfers/", payload, format="json")
        self.assertEqual(res_admin.status_code, status.HTTP_201_CREATED)

    def test_21_immutability(self):
        """21. Transfer record cannot be edited or deleted."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "5.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        transfer_id = res.data["id"]
        transfer = WarehouseTransfer.objects.get(pk=transfer_id)

        with self.assertRaises(ValueError):
            transfer.reason = "Modified Reason"
            transfer.save()

        with self.assertRaises(ValueError):
            transfer.delete()

    def test_22_atomic_rollback(self):
        """22. Failure inside transfer rolls back all inventory balance changes."""
        from unittest.mock import patch
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "10.00")
        self.client.force_authenticate(user=self.admin)

        with patch("inventory.transfer_services.AuditLog.objects.create", side_effect=RuntimeError("Simulated DB failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/inventory/transfers/",
                    {
                        "product": self.prod_piece.id,
                        "source_warehouse": self.wh_source.id,
                        "destination_warehouse": self.wh_dest.id,
                        "quantity": "5.000",
                        "unit": "piece",
                        "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                        "effective_date": timezone.localdate().isoformat(),
                    },
                    format="json",
                )

        src_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_source)
        self.assertEqual(src_bal.quantity_on_hand, Decimal("50.000"))
        self.assertEqual(WarehouseTransfer.objects.count(), 0)

    def test_23_idempotency(self):
        """23. Replaying request with same Idempotency-Key returns existing transfer."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "5.00")
        self.client.force_authenticate(user=self.admin)
        payload = {
            "product": self.prod_piece.id,
            "source_warehouse": self.wh_source.id,
            "destination_warehouse": self.wh_dest.id,
            "quantity": "5.000",
            "unit": "piece",
            "reason": WarehouseTransfer.REASON_REPLENISHMENT,
            "effective_date": timezone.localdate().isoformat(),
        }
        res1 = self.client.post(
            "/api/inventory/transfers/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="idemp-key-trf-12345",
        )
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        trf_num1 = res1.data["transfer_number"]

        res2 = self.client.post(
            "/api/inventory/transfers/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="idemp-key-trf-12345",
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["transfer_number"], trf_num1)

        # Confirm only 1 transfer created and stock deducted once (45 remaining, not 40)
        self.assertEqual(WarehouseTransfer.objects.count(), 1)
        src_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_source)
        self.assertEqual(src_bal.quantity_on_hand, Decimal("45.000"))

    def test_24_two_ledger_entries(self):
        """24. Transfer creates exactly TWO StockLedger entries."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "8.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "10.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        trf_num = res.data["transfer_number"]
        entries = StockLedger.objects.filter(reference=trf_num)
        self.assertEqual(entries.count(), 2)

    def test_25_correct_movement_types(self):
        """25. Correct movement types: WAREHOUSE_TRANSFER_OUT and WAREHOUSE_TRANSFER_IN."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "8.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "10.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REPLENISHMENT,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        trf_num = res.data["transfer_number"]

        out_entry = StockLedger.objects.get(reference=trf_num, warehouse=self.wh_source)
        self.assertEqual(out_entry.movement_type, StockLedger.WAREHOUSE_TRANSFER_OUT)
        self.assertEqual(out_entry.quantity_change, Decimal("-10.000"))
        self.assertEqual(out_entry.unit_cost, Decimal("8.00"))

        in_entry = StockLedger.objects.get(reference=trf_num, warehouse=self.wh_dest)
        self.assertEqual(in_entry.movement_type, StockLedger.WAREHOUSE_TRANSFER_IN)
        self.assertEqual(in_entry.quantity_change, Decimal("10.000"))
        self.assertEqual(in_entry.unit_cost, Decimal("8.00"))

    def test_26_audit_log(self):
        """26. AuditLog is created with product, warehouses, base qty, transfer value, and user."""
        self._set_stock(self.prod_piece, self.wh_source, "50.000", "8.00")
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "15.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_INTER_BRANCH,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        transfer_id = res.data["id"]
        audit = AuditLog.objects.filter(entity_type="WarehouseTransfer", entity_id=transfer_id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.admin)
        self.assertEqual(audit.metadata["source_warehouse_id"], self.wh_source.id)
        self.assertEqual(audit.metadata["destination_warehouse_id"], self.wh_dest.id)
        self.assertEqual(audit.metadata["base_quantity"], "15.000")
        self.assertEqual(audit.metadata["transfer_value"], "120.00")

    def test_27_total_inventory_valuation_consistency(self):
        """27. Total business inventory valuation remains consistent across transfers."""
        # Source: 100 pcs @ 12.00 = 1200.00
        # Destination: 50 pcs @ 8.00 = 400.00
        # Total initial valuation: 1600.00
        # Transfer 20 pcs from source to destination.
        # Transferred value: 20 * 12.00 = 240.00
        # Source becomes 80 pcs @ 12.00 = 960.00
        # Destination becomes: 50 * 8 + 20 * 12 = 640.00 / 70 pcs = 9.14 WAC (value = 70 * 9.14 = 639.80 with rounding)
        # Total stock remains 150 pcs.
        self._set_stock(self.prod_piece, self.wh_source, "100.000", "12.00")
        self._set_stock(self.prod_piece, self.wh_dest, "50.000", "8.00")

        initial_total_val = (Decimal("100.000") * Decimal("12.00")) + (Decimal("50.000") * Decimal("8.00"))
        self.assertEqual(initial_total_val, Decimal("1600.00"))

        self.client.force_authenticate(user=self.admin)
        self.client.post(
            "/api/inventory/transfers/",
            {
                "product": self.prod_piece.id,
                "source_warehouse": self.wh_source.id,
                "destination_warehouse": self.wh_dest.id,
                "quantity": "20.000",
                "unit": "piece",
                "reason": WarehouseTransfer.REASON_REBALANCING,
                "effective_date": timezone.localdate().isoformat(),
            },
            format="json",
        )

        src_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_source)
        dst_bal = InventoryBalance.objects.get(product=self.prod_piece, warehouse=self.wh_dest)

        self.assertEqual(src_bal.quantity_on_hand + dst_bal.quantity_on_hand, Decimal("150.000"))
        new_total_val = (src_bal.quantity_on_hand * src_bal.average_cost) + (dst_bal.quantity_on_hand * dst_bal.average_cost)
        # Due to 2 decimal place rounding on WAC: 80 * 12 = 960.00, 70 * 9.14 = 639.80, difference within a few paise
        self.assertAlmostEqual(float(new_total_val), float(initial_total_val), delta=0.50)
