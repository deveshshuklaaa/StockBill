"""Regression tests for the frontend integration fixes.

1. CORS preflight must accept the Idempotency-Key header. Without it the
   browser blocks purchase POSTs from the React app and the UI misreports
   the failure as "Django is not running" (network error with no response).
2. Product search must return the identifying data (MRP, SKU, attributes)
   the purchase dropdown needs to distinguish same-name variants.
3. The edit endpoint must keep returning 403 for staff even when the UI
   hides the button (backend remains authoritative).
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    Supplier,
    TaxRate,
)
from inventory.services import get_default_warehouse

User = get_user_model()


class CORSPreflightTests(APITestCase):
    """The Idempotency-Key header must survive the CORS preflight."""

    def test_preflight_allows_idempotency_key_header(self):
        response = self.client.options(
            "/api/purchase-invoices/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization,idempotency-key",
        )
        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("Access-Control-Allow-Headers", "")
        self.assertIn("idempotency-key", allowed.lower())
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://localhost:5173",
        )

    def test_preflight_allows_authorization_header(self):
        response = self.client.options(
            "/api/purchase-invoices/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )
        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("Access-Control-Allow-Headers", "")
        self.assertIn("authorization", allowed.lower())


class PurchaseProductSearchVariantTests(APITestCase):
    """Search results must expose enough data to tell same-name variants apart."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="search-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="search-staff", password="StrongPass123!", role="staff"
        )
        cls.category = Category.objects.create(code="packaged-food", name="Packaged Food")
        cls.net_weight = AttributeDefinition.objects.create(
            code="net_weight",
            name="Net Weight",
            data_type=AttributeDefinition.TYPE_DECIMAL,
            unit="kg",
            decimal_places=3,
        )
        cls.master_box = AttributeDefinition.objects.create(
            code="units_per_master_box",
            name="Units per Master Box",
            data_type=AttributeDefinition.TYPE_INTEGER,
        )
        for definition in (cls.net_weight, cls.master_box):
            CategoryAttribute.objects.create(
                category=cls.category, attribute_definition=definition, is_required=False
            )

        cls.chips_25g = Product.objects.create(
            name="Chheda's Yellow Banana Chips",
            mrp=Decimal("10.00"),
            base_unit=Product.UNIT_PIECE,
            catalogue_category=cls.category,
        )
        ProductAttributeValue.objects.create(
            product=cls.chips_25g,
            attribute_definition=cls.net_weight,
            value_number=Decimal("0.025"),
        )
        ProductAttributeValue.objects.create(
            product=cls.chips_25g,
            attribute_definition=cls.master_box,
            value_integer=192,
        )

        cls.chips_30g = Product.objects.create(
            name="Chheda's Yellow Banana Chips",
            mrp=Decimal("20.00"),
            base_unit=Product.UNIT_PIECE,
            catalogue_category=cls.category,
        )
        ProductAttributeValue.objects.create(
            product=cls.chips_30g,
            attribute_definition=cls.net_weight,
            value_number=Decimal("0.030"),
        )
        ProductAttributeValue.objects.create(
            product=cls.chips_30g,
            attribute_definition=cls.master_box,
            value_integer=120,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_search_returns_both_variants_with_identifying_fields(self):
        response = self.client_as(self.admin).get(
            "/api/products/", {"search": "Yellow Banana Chips"}
        )
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertEqual(len(rows), 2)

        by_mrp = {str(row["mrp"]): row for row in rows}
        self.assertIn("10.00", by_mrp)
        self.assertIn("20.00", by_mrp)

        light = by_mrp["10.00"]
        heavy = by_mrp["20.00"]
        self.assertEqual(Decimal(str(light["attributes"]["net_weight"])), Decimal("0.025"))
        self.assertEqual(Decimal(str(heavy["attributes"]["net_weight"])), Decimal("0.030"))
        self.assertEqual(light["attributes"]["units_per_master_box"], 192)
        self.assertEqual(heavy["attributes"]["units_per_master_box"], 120)
        self.assertEqual(light["base_unit"], "piece")

    def test_staff_search_also_returns_variant_identifiers(self):
        # Staff use a public serializer, but MRP/attributes remain exposed
        # because they identify variants; cost data is what stays hidden.
        response = self.client_as(self.staff).get(
            "/api/products/", {"search": "Yellow Banana Chips"}
        )
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("mrp", row)
            self.assertIn("attributes", row)
            self.assertNotIn("cost_price", row)

    def test_search_is_server_side_and_paginated(self):
        response = self.client_as(self.admin).get(
            "/api/products/", {"search": "Yellow Banana Chips", "page": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertIsNone(response.data["next"])


class ProductEditPermissionBoundaryTests(APITestCase):
    """The edit route's UI gating must not weaken the API boundary."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="edit-boundary-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="edit-boundary-staff", password="StrongPass123!", role="staff"
        )
        cls.product = Product.objects.create(
            name="Boundary Product",
            base_unit=Product.UNIT_PIECE,
            default_price=Decimal("10.00"),
            current_stock=0,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_staff_cannot_patch_product(self):
        response = self.client_as(self.staff).patch(
            f"/api/products/{self.product.pk}/",
            {"default_price": "99.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.default_price, Decimal("10.00"))

    def test_admin_can_patch_product(self):
        response = self.client_as(self.admin).patch(
            f"/api/products/{self.product.pk}/",
            {"default_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.default_price, Decimal("12.00"))

    def test_unauthenticated_cannot_patch_product(self):
        response = APIClient().patch(
            f"/api/products/{self.product.pk}/",
            {"default_price": "99.00"},
            format="json",
        )
        self.assertIn(response.status_code, {401, 403})


class PurchaseErrorHandlingTests(APITestCase):
    """The API responses for 401, 403, 400, and 409 must carry standard payloads."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="purchase-err-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="purchase-err-staff", password="StrongPass123!", role="staff"
        )
        cls.warehouse = get_default_warehouse()
        cls.supplier = Supplier.objects.create(
            name="Supplier for Error Tests",
            gstin="27AAACC1234A1Z5",
            state="Maharashtra",
            state_code="27",
        )
        cls.product = Product.objects.create(
            name="Error Test Product",
            base_unit=Product.UNIT_PIECE,
            default_price=Decimal("15.00"),
            cost_price=Decimal("10.00"),
            mrp=Decimal("20.00"),
            current_stock=0,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def valid_payload(self):
        return {
            "supplier": self.supplier.pk,
            "warehouse": self.warehouse.pk,
            "invoice_date": "2026-09-10",
            "tax_mode": "exclusive",
            "post": True,
            "line_items": [
                {
                    "product": self.product.pk,
                    "quantity": 10,
                    "purchase_unit": "piece",
                    "conversion_factor": 1,
                    "rate": "10.00",
                    "discount_amount": "0.00",
                }
            ],
        }

    def test_401_when_unauthenticated_posting_purchase(self):
        response = APIClient().post(
            "/api/purchase-invoices/", self.valid_payload(), format="json"
        )
        self.assertIn(response.status_code, {401, 403})

    def test_403_when_staff_posting_purchase(self):
        response = self.client_as(self.staff).post(
            "/api/purchase-invoices/", self.valid_payload(), format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_400_when_validation_fails(self):
        # Missing required fields like supplier and empty line_items
        invalid_payload = {
            "warehouse": self.warehouse.pk,
            "invoice_date": "2026-09-10",
            "line_items": [],
        }
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", invalid_payload, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("supplier", response.data)

    def test_409_when_idempotency_conflict(self):
        key = str(uuid.uuid4())
        payload = self.valid_payload()
        first = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(first.status_code, 201)

        # Same key with different payload triggers 409 Conflict
        conflicting_payload = self.valid_payload()
        conflicting_payload["line_items"][0]["rate"] = "25.00"
        second = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            conflicting_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(second.status_code, 409)
        self.assertIn("detail", second.data)

