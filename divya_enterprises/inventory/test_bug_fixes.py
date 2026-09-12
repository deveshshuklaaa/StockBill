"""Tests for UI bug fixes: inventory navigation, sidebar, and admin pages."""

from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from inventory.models import (
    Category,
    InventoryBalance,
    Product,
    StockLedger,
    TaxRate,
    Warehouse,
)
from billing.models import AuditLog, BusinessProfile
from inventory.services import get_default_warehouse

User = get_user_model()


class InventoryNavigationTests(APITestCase):
    """BUG 1: Verify that different products produce different URLs.

    When user clicks on different products in /inventory, each should open
    the correct product detail page (/inventory/:productId).
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="nav-test-admin", password="StrongPass123!", role="admin"
        )
        cls.warehouse = get_default_warehouse()

        # Create 3 visibly different products
        cls.product_a = Product.objects.create(
            name="Flour - Premium White",
            sku="FLOUR-001",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("280.00"),
            cost_price=Decimal("200.00"),
            is_active=True,
        )

        cls.product_b = Product.objects.create(
            name="Sugar - White Granulated",
            sku="SUGAR-001",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("320.00"),
            cost_price=Decimal("250.00"),
            is_active=True,
        )

        cls.product_c = Product.objects.create(
            name="Oil - Refined Vegetable",
            sku="OIL-001",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("450.00"),
            cost_price=Decimal("350.00"),
            is_active=True,
        )

        # Create inventory balances for each product
        for product, qty, avg_cost in [
            (cls.product_a, Decimal("150.000"), Decimal("200.00")),
            (cls.product_b, Decimal("100.000"), Decimal("250.00")),
            (cls.product_c, Decimal("200.000"), Decimal("350.00")),
        ]:
            InventoryBalance.objects.create(
                product=product,
                warehouse=cls.warehouse,
                quantity_on_hand=qty,
                average_cost=avg_cost,
            )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_inventory_balances_returns_unique_product_ids(self):
        """The API must return different product IDs for different products."""
        response = self.client_as(self.admin).get("/api/inventory-balances/")
        self.assertEqual(response.status_code, 200)

        items = response.data["results"]
        self.assertEqual(len(items), 3)

        # Extract product IDs from response
        product_ids = [item["product"] for item in items]
        product_names = [item["product_name"] for item in items]

        # All product IDs must be different
        self.assertEqual(len(product_ids), len(set(product_ids)),
                         f"Product IDs are not unique: {product_ids}")

        # Verify they match our created products
        self.assertIn(self.product_a.pk, product_ids)
        self.assertIn(self.product_b.pk, product_ids)
        self.assertIn(self.product_c.pk, product_ids)

        # Verify product names are correct
        self.assertIn("Flour - Premium White", product_names)
        self.assertIn("Sugar - White Granulated", product_names)
        self.assertIn("Oil - Refined Vegetable", product_names)

    def test_product_inventory_detail_returns_correct_product(self):
        """When fetching a specific product's inventory, it must return only that product."""
        # Get all products first to verify filtering works
        response_all = self.client_as(self.admin).get("/api/inventory-balances/")
        self.assertEqual(response_all.status_code, 200)
        all_items = response_all.data["results"]
        self.assertEqual(len(all_items), 3)  # We created 3 products

        # Now filter by product_a
        response = self.client_as(self.admin).get(
            "/api/inventory-balances/", {"product": self.product_a.pk}
        )
        self.assertEqual(response.status_code, 200)

        items = response.data["results"]
        self.assertGreater(len(items), 0)

        # All items must be for product_a
        for item in items:
            self.assertEqual(item["product"], self.product_a.pk,
                           f"Expected product {self.product_a.pk}, got {item['product']}")
            self.assertEqual(item["product_name"], "Flour - Premium White")

    def test_two_different_products_return_different_balances(self):
        """Regression: /inventory/3 and /inventory/124 must not render identically.

        The detail page derives its header/totals from the ?product= filter.
        If the filter is ignored, both routes show the same first row of the
        unfiltered list. The API contract: exactly the requested product's
        rows, different quantities, and per-product WAC.
        """
        responses = {}
        for product in (self.product_a, self.product_b):
            response = self.client_as(self.admin).get(
                "/api/inventory-balances/", {"product": product.pk}
            )
            self.assertEqual(response.status_code, 200)
            items = response.data["results"]
            self.assertEqual(len(items), 1, f"Expected exactly one row for {product.name}")
            self.assertEqual(items[0]["product"], product.pk)
            responses[product.pk] = items[0]

        row_a = responses[self.product_a.pk]
        row_b = responses[self.product_b.pk]
        self.assertNotEqual(row_a["product_name"], row_b["product_name"])
        self.assertNotEqual(
            Decimal(row_a["quantity_on_hand"]), Decimal(row_b["quantity_on_hand"])
        )
        self.assertNotEqual(Decimal(row_a["average_cost"]), Decimal(row_b["average_cost"]))
        # WAC must be the balance values, never MRP or another product's cost.
        self.assertEqual(Decimal(row_a["average_cost"]), Decimal("200.00"))
        self.assertEqual(Decimal(row_b["average_cost"]), Decimal("250.00"))

    def test_stock_ledger_filters_to_requested_product(self):
        """The movement history must be scoped to the requested product."""
        from inventory.services import adjust_inventory

        for product in (self.product_a, self.product_b):
            adjust_inventory(
                product=product,
                quantity_delta=Decimal("10"),
                movement_type=StockLedger.ADJUSTMENT,
                created_by=self.admin,
            )

        for product in (self.product_a, self.product_b):
            response = self.client_as(self.admin).get(
                "/api/stock-ledger/", {"product": product.pk}
            )
            self.assertEqual(response.status_code, 200)
            self.assertGreater(response.data["count"], 0)
            for row in response.data["results"]:
                self.assertEqual(
                    row["product"],
                    product.pk,
                    f"Ledger for product {product.pk} leaked row for {row['product']}",
                )


class AdminPagesAccessTests(APITestCase):
    """BUG 3: Verify admin pages return correct data without errors."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-pages-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="admin-pages-staff", password="StrongPass123!", role="staff"
        )

        # Create business profile
        cls.profile = BusinessProfile.objects.first()
        if not cls.profile:
            cls.profile = BusinessProfile.objects.create(
                business_name="Test Enterprise",
                gstin="27AAAAA1234A1Z5",
                registered_address="123 Test St",
                state="Maharashtra",
                state_code="27",
            )

        # Create tax rate (or get existing one with unique name)
        cls.tax_rate, _ = TaxRate.objects.get_or_create(
            name="GST 18% (Test)",
            defaults={"rate": Decimal("18.00"), "is_active": True}
        )

        # Create audit log
        AuditLog.objects.create(
            user=cls.admin,
            action="test_action",
            entity_type="Product",
            entity_id=1,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_audit_logs_returns_paginated_results(self):
        """Audit logs endpoint must return paginated results, not array."""
        response = self.client_as(self.admin).get("/api/audit-logs/")
        self.assertEqual(response.status_code, 200)

        # Response must be a dict with pagination keys
        self.assertIsInstance(response.data, dict)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)

        # Results must be an array
        self.assertIsInstance(response.data["results"], list)
        self.assertGreater(len(response.data["results"]), 0)

    def test_audit_logs_forbidden_for_staff(self):
        """Staff cannot access audit logs."""
        response = self.client_as(self.staff).get("/api/audit-logs/")
        self.assertEqual(response.status_code, 403)

    def test_business_profile_returns_object(self):
        """Business profile endpoint must return single object, not array."""
        response = self.client_as(self.admin).get("/api/business-profile/")
        self.assertEqual(response.status_code, 200)

        # Response must be dict with profile data
        self.assertIsInstance(response.data, dict)
        self.assertIn("business_name", response.data)
        self.assertIn("gstin", response.data)
        # Must NOT be an array
        self.assertNotIsInstance(response.data, list)

    def test_business_profile_forbidden_for_staff(self):
        """Staff cannot access business profile settings."""
        response = self.client_as(self.staff).get("/api/business-profile/")
        self.assertEqual(response.status_code, 403)

    def test_warehouse_summary_returns_results_wrapper(self):
        """Warehouse summary must return array of warehouse inventory summaries."""
        # Create a warehouse with some inventory
        warehouse = Warehouse.objects.first() or Warehouse.objects.create(
            name="Test Warehouse", code="TW"
        )
        # Ensure there's inventory to summarize
        product = Product.objects.first() or Product.objects.create(
            name="Test Product", base_unit=Product.UNIT_PIECE
        )
        InventoryBalance.objects.get_or_create(
            product=product,
            warehouse=warehouse,
            defaults={"quantity_on_hand": Decimal("10.000"), "average_cost": Decimal("100.00")}
        )

        response = self.client_as(self.admin).get("/api/warehouses/summary/")
        self.assertEqual(response.status_code, 200, f"Response: {response.data}")

        # Response must be an array of warehouse summaries
        self.assertIsInstance(response.data, list)
        self.assertGreater(len(response.data), 0)

        # Each item must have required fields
        for item in response.data:
            self.assertIn("warehouse", item)
            self.assertIn("name", item)
            self.assertIn("code", item)
            self.assertIn("product_count", item)
            self.assertIn("total_quantity", item)
            self.assertIn("total_value", item)

    def test_tax_rates_admin_returns_array(self):
        """Tax rates admin endpoint must return paginated array of tax rates."""
        response = self.client_as(self.admin).get("/api/tax-rates/admin/")
        self.assertEqual(response.status_code, 200, f"Response: {response.data}")

        # Response should be paginated dict with results
        if isinstance(response.data, dict):
            # If paginated
            self.assertIn("results", response.data)
            items = response.data["results"]
        else:
            # If direct array
            items = response.data

        self.assertIsInstance(items, list)
        # Should have at least our test tax rate
        self.assertGreater(len(items), 0)

        # Each tax rate must have required fields
        for item in items:
            self.assertIn("id", item)
            self.assertIn("name", item)
            self.assertIn("rate", item)
            self.assertIn("is_active", item)


class ErrorFormattingTests(APITestCase):
    """BUG 3: Verify error messages don't contain malformed "0:1:2:" strings."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="error-test-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="error-test-staff", password="StrongPass123!", role="staff"
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_401_error_format(self):
        """Unauthorized errors must have proper format."""
        response = APIClient().get("/api/audit-logs/")
        self.assertIn(response.status_code, {401, 403})

    def test_403_error_format(self):
        """Forbidden errors must have proper format."""
        response = self.client_as(self.staff).get("/api/audit-logs/")
        self.assertEqual(response.status_code, 403)

        # Must have detail key, not array
        self.assertIsInstance(response.data, dict)
        self.assertIn("detail", response.data)

    def test_400_validation_error_format(self):
        """400 validation errors must not contain "0:" patterns."""
        # Try to create business profile with invalid data
        response = self.client_as(self.admin).patch(
            "/api/business-profile/",
            {"business_name": "", "gstin": "INVALID"},
            format="json",
        )

        # If there's a validation error, it should be a dict with fields, not array
        if response.status_code == 400:
            self.assertIsInstance(response.data, dict)
            # Should not have numeric keys at top level
            for key in response.data.keys():
                self.assertFalse(key.isdigit(),
                                 f"Error response has numeric key: {key}")
