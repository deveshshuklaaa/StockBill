"""Tests for units_per_master_box metadata field on Product."""

from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    StockLedger,
    TaxRate,
    Warehouse,
)
from inventory.services import get_default_warehouse

User = get_user_model()


class UnitsPerMasterBoxApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-user", password="Pass123!Secure", role="admin"
        )
        self.staff = User.objects.create_user(
            username="staff-user", password="Pass123!Secure", role="staff"
        )
        self.warehouse = get_default_warehouse()
        self.tax, _ = TaxRate.objects.get_or_create(
            name="GST 18%", defaults={"rate": Decimal("18.00")}
        )
        self.category = Category.objects.create(code="snack-food", name="Snack Food")
        self.master_box_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.create(
            category=self.category,
            attribute_definition=self.master_box_attr,
            is_required=False,
        )

    def client_as(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def test_create_product_with_units_per_master_box(self):
        """Admin can create a product with units_per_master_box."""
        payload = {
            "name": "Chheda Yellow Banana Wafers 200g",
            "base_unit": "piece",
            "catalogue_category": self.category.pk,
            "units_per_master_box": 24,
            "mrp": "65.00",
            "default_price": "60.00",
            "cost_price": "50.00",
            "tax": self.tax.pk,
        }
        res = self.client_as(self.admin).post("/api/products/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["units_per_master_box"], 24)
        self.assertEqual(res.data["attributes"]["units_per_master_box"], 24)

        product = Product.objects.get(pk=res.data["id"])
        self.assertEqual(product.units_per_master_box, 24)
        # Invariant: inventory quantities untouched
        self.assertEqual(product.current_stock, Decimal("0.000"))

    def test_edit_product_units_per_master_box(self):
        """Editing units_per_master_box updates metadata without affecting stock."""
        product = Product.objects.create(
            name="Cream Wafers",
            base_unit="piece",
            catalogue_category=self.category,
            current_stock=Decimal("100.000"),
            mrp=Decimal("30.00"),
            tax=self.tax,
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.master_box_attr,
            value_integer=24,
        )

        res = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {"units_per_master_box": 48},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["units_per_master_box"], 48)
        self.assertEqual(res.data["attributes"]["units_per_master_box"], 48)

        product.refresh_from_db()
        self.assertEqual(product.units_per_master_box, 48)
        self.assertEqual(product.current_stock, Decimal("100.000"))

    def test_create_and_update_leave_blank(self):
        """Leaving units_per_master_box blank or null is valid for products without pack size."""
        # Create without units_per_master_box
        payload = {
            "name": "Single Loose Item",
            "base_unit": "piece",
            "catalogue_category": self.category.pk,
            "mrp": "10.00",
            "tax": self.tax.pk,
        }
        res = self.client_as(self.admin).post("/api/products/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data["units_per_master_box"])

        pid = res.data["id"]
        # Update with explicit null
        res2 = self.client_as(self.admin).patch(
            f"/api/products/{pid}/",
            {"units_per_master_box": None},
            format="json",
        )
        self.assertEqual(res2.status_code, 200, res2.data)
        self.assertIsNone(res2.data["units_per_master_box"])

    def test_reject_zero_and_negative_units_per_master_box(self):
        """Units per master box must be a positive integer."""
        for invalid_val in [0, -1, -24]:
            payload = {
                "name": "Invalid Box Product",
                "base_unit": "piece",
                "catalogue_category": self.category.pk,
                "units_per_master_box": invalid_val,
                "tax": self.tax.pk,
            }
            res = self.client_as(self.admin).post("/api/products/", payload, format="json")
            self.assertEqual(res.status_code, 400, f"Expected 400 for {invalid_val}")
            self.assertIn("units_per_master_box", res.data)

    def test_reject_fractional_units_per_master_box(self):
        """Units per master box rejects non-integer values."""
        payload = {
            "name": "Fractional Box Product",
            "base_unit": "piece",
            "catalogue_category": self.category.pk,
            "units_per_master_box": "24.5",
            "tax": self.tax.pk,
        }
        res = self.client_as(self.admin).post("/api/products/", payload, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("units_per_master_box", res.data)

    def test_staff_reads_units_per_master_box(self):
        """Staff serializer exposes units_per_master_box as read-only."""
        product = Product.objects.create(
            name="Staff View Product",
            base_unit="piece",
            catalogue_category=self.category,
            current_stock=Decimal("50.000"),
            mrp=Decimal("20.00"),
            tax=self.tax,
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.master_box_attr,
            value_integer=36,
        )
        res = self.client_as(self.staff).get(f"/api/products/{product.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["units_per_master_box"], 36)
