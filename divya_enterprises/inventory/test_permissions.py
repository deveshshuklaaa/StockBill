from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from customers.models import Customer
from inventory.models import Product, TaxRate

User = get_user_model()


class CatalogCustomerPermissionTests(APITestCase):
    """Regression tests for role-based authorization on catalog and customer endpoints.

    Covers the case-normalized role bug: users stored with role values like
    "ADMIN"/"STAFF" must receive the same access as "admin"/"staff".
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username="perm-admin",
            password="StrongPass123!",
            role="ADMIN",
            is_staff=True,
            is_superuser=True,
        )
        self.staff = User.objects.create_user(
            username="perm-staff",
            password="StrongPass123!",
            role="STAFF",
            is_staff=True,
        )
        self.lowercase_admin = User.objects.create_user(
            username="perm-admin-lower",
            password="StrongPass123!",
            role="admin",
        )
        self.tax = TaxRate.objects.create(name="18%", rate=Decimal("18.00"))
        self.existing_product = Product.objects.create(
            name="Permission Product",
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=100,
            cost_price=60,
            tax=self.tax,
            current_stock=5,
        )
        self.existing_customer = Customer.objects.create(
            name="Permission Customer",
            contact_info="9999999999",
            state_code="29",
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def product_payload(self, name):
        return {
            "name": name,
            "unit_type": Product.UNIT_PIECE,
            "unit_conversion_factor": "1",
            "default_price": "100.00",
            "cost_price": "60.00",
            "current_stock": "0",
            "low_stock_threshold": "0",
        }

    # --- ADMIN: products ---

    def test_uppercase_admin_can_list_products(self):
        response = self.client_as(self.admin).get("/api/products/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["results"]), 1)

    def test_uppercase_admin_can_create_product(self):
        response = self.client_as(self.admin).post(
            "/api/products/",
            self.product_payload("Admin Created Product"),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data["is_active"] is None)
        self.assertIn("cost_price", response.data)

    def test_uppercase_admin_can_update_product(self):
        response = self.client_as(self.admin).patch(
            f"/api/products/{self.existing_product.pk}/",
            {"default_price": "120.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.default_price, Decimal("120.00"))

    def test_uppercase_admin_archive_is_ignored_by_destroy(self):
        # Destroy archives the product (sets is_active=False) instead of deleting.
        response = self.client_as(self.admin).delete(
            f"/api/products/{self.existing_product.pk}/"
        )
        self.assertEqual(response.status_code, 204)
        self.existing_product.refresh_from_db()
        self.assertFalse(self.existing_product.is_active)
        self.assertTrue(Product.objects.filter(pk=self.existing_product.pk).exists())

    def test_uppercase_admin_sees_cost_price_in_product_list(self):
        response = self.client_as(self.admin).get("/api/products/")
        row = response.data["results"][0]
        self.assertIn("cost_price", row)

    # --- ADMIN: customers ---

    def test_uppercase_admin_can_list_customers(self):
        response = self.client_as(self.admin).get("/api/customers/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["results"]), 1)

    def test_uppercase_admin_can_create_customer(self):
        response = self.client_as(self.admin).post(
            "/api/customers/",
            {"name": "Admin Created Customer", "contact_info": "8888888888"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["name"], "Admin Created Customer")

    def test_uppercase_admin_can_update_customer(self):
        response = self.client_as(self.admin).patch(
            f"/api/customers/{self.existing_customer.pk}/",
            {"contact_info": "7777777777"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.existing_customer.refresh_from_db()
        self.assertEqual(self.existing_customer.contact_info, "7777777777")

    # --- STAFF: products (restricted per policy) ---

    def test_uppercase_staff_can_list_products_but_not_see_cost(self):
        response = self.client_as(self.staff).get("/api/products/")
        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertNotIn("cost_price", row)

    def test_uppercase_staff_cannot_create_product(self):
        response = self.client_as(self.staff).post(
            "/api/products/",
            self.product_payload("Staff Created Product"),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_uppercase_staff_cannot_update_product(self):
        response = self.client_as(self.staff).patch(
            f"/api/products/{self.existing_product.pk}/",
            {"default_price": "999.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_uppercase_staff_cannot_archive_product(self):
        response = self.client_as(self.staff).delete(
            f"/api/products/{self.existing_product.pk}/"
        )
        self.assertEqual(response.status_code, 403)
        self.existing_product.refresh_from_db()
        self.assertTrue(self.existing_product.is_active)

    # --- STAFF: customers (restricted per policy) ---

    def test_uppercase_staff_can_list_customers(self):
        response = self.client_as(self.staff).get("/api/customers/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["results"]), 1)

    def test_uppercase_staff_cannot_create_customer(self):
        response = self.client_as(self.staff).post(
            "/api/customers/",
            {"name": "Staff Created Customer"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_uppercase_staff_cannot_update_customer(self):
        response = self.client_as(self.staff).patch(
            f"/api/customers/{self.existing_customer.pk}/",
            {"contact_info": "0000000000"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    # --- lowercase parity + authentication boundary ---

    def test_lowercase_admin_parity(self):
        response = self.client_as(self.lowercase_admin).get("/api/products/")
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_requests_are_rejected(self):
        response = APIClient().get("/api/products/")
        self.assertIn(response.status_code, {401, 403})

    def test_default_role_user_cannot_write_catalog(self):
        # A fresh user with no explicit admin role must not gain catalog write access.
        default_user = User.objects.create_user(
            username="perm-default", password="StrongPass123!"
        )
        response = self.client_as(default_user).post(
            "/api/products/",
            self.product_payload("Default Role Product"),
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class RoleNormalizationTests(APITestCase):
    def test_normalized_role_is_case_insensitive(self):
        for raw, expected in (
            ("ADMIN", "admin"),
            ("admin", "admin"),
            ("Staff", "staff"),
            (" staff ", "staff"),
        ):
            user = User(username=f"norm-{raw.strip()}-{expected}")
            user.role = raw
            self.assertEqual(user.normalized_role, expected)

    def test_blank_role_normalizes_to_empty(self):
        user = User(username="norm-blank", role="")
        self.assertEqual(user.normalized_role, "")
