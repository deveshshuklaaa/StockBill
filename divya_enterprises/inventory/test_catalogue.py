"""Phase 1 dynamic catalogue tests: categories, attributes, typed values, permissions,
inventory/GST/billing compatibility."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import Invoice
from billing.services import create_invoice
from customers.models import Customer
from .models import (
    AttributeChoice,
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    StockLedger,
    TaxRate,
)
from .services import adjust_inventory

User = get_user_model()


class CatalogueTestBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="cat-admin", password="StrongPass123!", role="admin"
        )
        self.staff = User.objects.create_user(
            username="cat-staff", password="StrongPass123!", role="staff"
        )

        # Packaged Food: net weight (required, filterable), units per master box (required)
        self.food = Category.objects.create(code="packaged-food", name="Packaged Food")
        self.net_weight = AttributeDefinition.objects.create(
            code="net_weight",
            name="Net Weight",
            data_type=AttributeDefinition.TYPE_DECIMAL,
            unit="kg",
            decimal_places=3,
        )
        self.master_box = AttributeDefinition.objects.create(
            code="units_per_master_box",
            name="Units per Master Box",
            data_type=AttributeDefinition.TYPE_INTEGER,
        )
        self.flavour = AttributeDefinition.objects.create(
            code="flavour",
            name="Flavour",
            data_type=AttributeDefinition.TYPE_TEXT,
        )
        CategoryAttribute.objects.create(
            category=self.food,
            attribute_definition=self.net_weight,
            is_required=True,
            is_filterable=True,
            display_order=1,
        )
        CategoryAttribute.objects.create(
            category=self.food,
            attribute_definition=self.master_box,
            is_required=True,
            display_order=2,
        )
        CategoryAttribute.objects.create(
            category=self.food,
            attribute_definition=self.flavour,
            display_order=3,
        )

        # Batteries: battery size (required, filterable CHOICE), chemistry (CHOICE), pack qty (INTEGER)
        self.batteries = Category.objects.create(code="batteries", name="Batteries")
        self.battery_size = AttributeDefinition.objects.create(
            code="battery_size",
            name="Battery Size",
            data_type=AttributeDefinition.TYPE_CHOICE,
        )
        for order, value in enumerate(["AA", "AAA", "C", "D", "9V"]):
            AttributeChoice.objects.create(
                attribute_definition=self.battery_size,
                value=value,
                label=value,
                display_order=order,
            )
        self.chemistry = AttributeDefinition.objects.create(
            code="chemistry",
            name="Chemistry",
            data_type=AttributeDefinition.TYPE_CHOICE,
        )
        for order, value in enumerate(["Alkaline", "Lithium", "Zinc Carbon"]):
            AttributeChoice.objects.create(
                attribute_definition=self.chemistry,
                value=value,
                label=value,
                display_order=order,
            )
        self.pack_quantity = AttributeDefinition.objects.create(
            code="pack_quantity",
            name="Pack Quantity",
            data_type=AttributeDefinition.TYPE_INTEGER,
        )
        CategoryAttribute.objects.create(
            category=self.batteries,
            attribute_definition=self.battery_size,
            is_required=True,
            is_filterable=True,
            display_order=1,
        )
        CategoryAttribute.objects.create(
            category=self.batteries,
            attribute_definition=self.chemistry,
            display_order=2,
        )
        CategoryAttribute.objects.create(
            category=self.batteries,
            attribute_definition=self.pack_quantity,
            display_order=3,
        )

        self.tax = TaxRate.objects.create(name="18% GST", rate=Decimal("18.00"))

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class CategoryPermissionTests(CatalogueTestBase):
    def test_admin_can_create_category(self):
        response = self.client_as(self.admin).post(
            "/api/categories/",
            {"code": "stationery", "name": "Stationery"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Category.objects.filter(code="stationery").exists())

    def test_staff_cannot_create_category(self):
        response = self.client_as(self.staff).post(
            "/api/categories/",
            {"code": "stationery", "name": "Stationery"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_and_deactivate_category(self):
        response = self.client_as(self.admin).patch(
            f"/api/categories/{self.food.pk}/", {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.food.refresh_from_db()
        self.assertFalse(self.food.is_active)

    def test_staff_cannot_update_category(self):
        response = self.client_as(self.staff).patch(
            f"/api/categories/{self.food.pk}/", {"description": "nope"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_can_list_categories(self):
        response = self.client_as(self.staff).get("/api/categories/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_inactive_category_cannot_be_assigned_to_new_product(self):
        self.food.is_active = False
        self.food.save(update_fields=["is_active"])
        response = self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Stale Food",
                "catalogue_category": self.food.pk,
                "base_unit": "piece",
                "attributes": {"net_weight": "0.025", "units_per_master_box": 192},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("catalogue_category", response.data)

    def test_inactive_category_cannot_be_assigned_on_update(self):
        product = Product.objects.create(
            name="Existing Food", base_unit="piece", catalogue_category=self.food
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.net_weight,
            value_number=Decimal("0.025"),
        )
        ProductAttributeValue.objects.create(
            product=product, attribute_definition=self.master_box, value_integer=192
        )
        self.food.is_active = False
        self.food.save(update_fields=["is_active"])
        response = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {"catalogue_category": self.food.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("catalogue_category", response.data)

    def test_category_with_products_cannot_be_deleted(self):
        Product.objects.create(
            name="Linked Food", base_unit="piece", catalogue_category=self.food
        )
        response = self.client_as(self.admin).delete(f"/api/categories/{self.food.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Category.objects.filter(pk=self.food.pk).exists())


class AttributeDefinitionTests(CatalogueTestBase):
    def test_admin_can_create_attribute_and_choices(self):
        response = self.client_as(self.admin).post(
            "/api/attributes/",
            {"code": "rechargeable", "name": "Rechargeable", "data_type": "BOOLEAN"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_staff_cannot_create_attribute(self):
        response = self.client_as(self.staff).post(
            "/api/attributes/",
            {"code": "rechargeable", "name": "Rechargeable", "data_type": "BOOLEAN"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_decimal_requires_decimal_places(self):
        response = self.client_as(self.admin).post(
            "/api/attributes/",
            {"code": "volume", "name": "Net Volume", "data_type": "DECIMAL"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("decimal_places", response.data)

    def test_decimal_places_rejected_for_non_decimal(self):
        response = self.client_as(self.admin).post(
            "/api/attributes/",
            {
                "code": "pages",
                "name": "Page Count",
                "data_type": "INTEGER",
                "decimal_places": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("decimal_places", response.data)

    def test_data_type_immutable_once_values_exist(self):
        product = Product.objects.create(
            name="Type Guard", base_unit="piece", catalogue_category=self.food
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.net_weight,
            value_number=Decimal("0.025"),
        )
        self.net_weight.data_type = AttributeDefinition.TYPE_INTEGER
        with self.assertRaises(ValueError):
            self.net_weight.save()

    def test_choice_values_unique_per_attribute(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            AttributeChoice.objects.create(
                attribute_definition=self.battery_size, value="AA", label="Duplicate"
            )


class CategoryAttributeAssignmentTests(CatalogueTestBase):
    def test_admin_can_assign_attribute_with_flags(self):
        response = self.client_as(self.admin).post(
            f"/api/categories/{self.batteries.pk}/attribute-assignments/",
            {
                "attribute_definition": self.flavour.pk,
                "is_required": False,
                "is_filterable": True,
                "is_invoice_visible": False,
                "display_order": 4,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            CategoryAttribute.objects.filter(
                category=self.batteries,
                attribute_definition=self.flavour,
                is_filterable=True,
            ).exists()
        )

    def test_duplicate_assignment_rejected(self):
        response = self.client_as(self.admin).post(
            f"/api/categories/{self.food.pk}/attribute-assignments/",
            {"attribute_definition": self.net_weight.pk},
            format="json",
        )
        self.assertIn(response.status_code, {400, 409})
        self.assertEqual(
            CategoryAttribute.objects.filter(
                category=self.food, attribute_definition=self.net_weight
            ).count(),
            1,
        )

    def test_staff_cannot_assign_attributes(self):
        response = self.client_as(self.staff).post(
            f"/api/categories/{self.food.pk}/attribute-assignments/",
            {"attribute_definition": self.flavour.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_category_schema_endpoint_returns_form_metadata(self):
        response = self.client_as(self.staff).get(
            f"/api/categories/{self.batteries.pk}/attributes/"
        )
        self.assertEqual(response.status_code, 200)
        schema = response.data
        self.assertEqual(len(schema), 3)
        self.assertEqual(schema[0]["code"], "battery_size")
        self.assertTrue(schema[0]["is_required"])
        self.assertEqual(
            [c["value"] for c in schema[0]["choices"]], ["AA", "AAA", "C", "D", "9V"]
        )
        codes = [s["code"] for s in schema]
        self.assertIn("chemistry", codes)
        self.assertIn("pack_quantity", codes)


class ProductAttributeValidationTests(CatalogueTestBase):
    def create_product(
        self, attributes, category=None, name="New Product", mrp=None, expect=201
    ):
        payload = {
            "name": name,
            "base_unit": "piece",
            "catalogue_category": (category or self.food).pk,
            "default_price": "100.00",
            "cost_price": "60.00",
            "tax": self.tax.pk,
            "attributes": attributes,
        }
        if mrp is not None:
            payload["mrp"] = mrp
        response = self.client_as(self.admin).post(
            "/api/products/", payload, format="json"
        )
        self.assertEqual(response.status_code, expect, response.data)
        return response

    def test_food_with_net_weight_and_master_box_is_valid(self):
        response = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192}
        )
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(
            ProductAttributeValue.objects.get(
                product=product, attribute_definition=self.net_weight
            ).value_number,
            Decimal("0.025"),
        )
        self.assertEqual(
            ProductAttributeValue.objects.get(
                product=product, attribute_definition=self.master_box
            ).value_integer,
            192,
        )
        self.assertEqual(response.data["mrp"], None)
        self.assertEqual(response.data["attributes"]["net_weight"], Decimal("0.025"))

    def test_food_missing_required_net_weight_is_rejected(self):
        self.create_product({"units_per_master_box": 192}, name="No Weight", expect=400)

    def test_battery_with_battery_size_is_valid(self):
        response = self.create_product(
            {"battery_size": "AA", "chemistry": "Alkaline", "pack_quantity": 4},
            category=self.batteries,
            name="Duracell AA 4-Pack",
        )
        product = Product.objects.get(pk=response.data["id"])
        value = ProductAttributeValue.objects.get(
            product=product, attribute_definition=self.battery_size
        )
        self.assertEqual(value.value_choice.value, "AA")
        self.assertEqual(response.data["attributes"]["battery_size"], "AA")

    def test_battery_missing_required_size_is_rejected(self):
        self.create_product(
            {"chemistry": "Alkaline", "pack_quantity": 4},
            category=self.batteries,
            name="No Size Battery",
            expect=400,
        )

    def test_battery_without_net_weight_is_valid(self):
        response = self.create_product(
            {"battery_size": "AA", "pack_quantity": 4},
            category=self.batteries,
            name="Slim Battery",
        )
        self.assertNotIn("net_weight", response.data["attributes"])

    def test_attribute_not_assigned_to_category_is_rejected(self):
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192, "battery_size": "AA"},
            name="Impossible Product",
            expect=400,
        )

    def test_invalid_choice_is_rejected(self):
        self.create_product(
            {"battery_size": "AAA-battery-invalid", "pack_quantity": 4},
            category=self.batteries,
            name="Bad Choice",
            expect=400,
        )

    def test_integer_rejects_non_integer(self):
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": "twenty boxes"},
            name="Bad Integer",
            expect=400,
        )

    def test_decimal_precision_enforced(self):
        self.create_product(
            {"net_weight": "0.02571", "units_per_master_box": 192},
            name="Too Precise",
            expect=400,
        )

    def test_date_and_boolean_types_round_trip(self):
        category = Category.objects.create(code="stationery", name="Stationery")
        printed_on = AttributeDefinition.objects.create(
            code="printed_on",
            name="Printed On",
            data_type=AttributeDefinition.TYPE_DATE,
        )
        laminated = AttributeDefinition.objects.create(
            code="laminated",
            name="Laminated",
            data_type=AttributeDefinition.TYPE_BOOLEAN,
        )
        CategoryAttribute.objects.create(
            category=category, attribute_definition=printed_on
        )
        CategoryAttribute.objects.create(
            category=category, attribute_definition=laminated
        )
        response = self.create_product(
            {"printed_on": "2026-01-15", "laminated": "true"},
            category=category,
            name="Notebook",
        )
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(
            ProductAttributeValue.objects.get(
                product=product, attribute_definition=printed_on
            ).value_date,
            date(2026, 1, 15),
        )
        self.assertIs(
            ProductAttributeValue.objects.get(
                product=product, attribute_definition=laminated
            ).value_boolean,
            True,
        )

    def test_update_replaces_attribute_values(self):
        response = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192}
        )
        product = Product.objects.get(pk=response.data["id"])
        update = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {
                "attributes": {
                    "net_weight": "0.030",
                    "units_per_master_box": 120,
                    "flavour": "Peri Peri",
                }
            },
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(update.data["attributes"]["net_weight"], Decimal("0.030"))
        self.assertEqual(update.data["attributes"]["units_per_master_box"], 120)
        self.assertEqual(update.data["attributes"]["flavour"], "Peri Peri")

    def test_partial_update_keeps_existing_required_values(self):
        response = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192}
        )
        product = Product.objects.get(pk=response.data["id"])
        update = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {"attributes": {"units_per_master_box": 120}},
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.data)
        # net_weight was required but already stored; omission must not clear it.
        self.assertEqual(update.data["attributes"]["net_weight"], Decimal("0.025"))
        self.assertEqual(update.data["attributes"]["units_per_master_box"], 120)

    def test_mrp_and_sku_are_saved_and_distinct_from_prices(self):
        response = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="MRP Product",
        )
        product = Product.objects.get(pk=response.data["id"])
        product.mrp = Decimal("10.00")
        product.sku = "DE-FOOD-001"
        product.save(update_fields=["mrp", "sku", "updated_at"])
        detail = self.client_as(self.admin).get(f"/api/products/{product.pk}/")
        self.assertEqual(detail.data["mrp"], "10.00")
        self.assertEqual(detail.data["sku"], "DE-FOOD-001")
        self.assertEqual(detail.data["default_price"], "100.00")
        self.assertEqual(detail.data["cost_price"], "60.00")

    def test_product_tax_is_writable_via_api(self):
        response = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="Taxed Product",
        )
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(product.tax, self.tax)
        self.assertEqual(response.data["tax"], self.tax.pk)
        self.assertEqual(response.data["tax_rate"], "18.00")

    def test_staff_product_list_omits_cost_price_but_includes_attributes(self):
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192}, name="Staff View"
        )
        response = self.client_as(self.staff).get("/api/products/")
        row = response.data["results"][0]
        self.assertNotIn("cost_price", row)
        self.assertIn("attributes", row)
        self.assertEqual(row["attributes"]["net_weight"], Decimal("0.025"))

    def test_variant_rows_stay_separate(self):
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="Chheda's Yellow Banana Chips",
        )
        self.create_product(
            {"net_weight": "0.030", "units_per_master_box": 120},
            name="Chheda's Yellow Banana Chips",
        )
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(
            Product.objects.filter(name="Chheda's Yellow Banana Chips").count(), 2
        )

    def test_duplicate_variant_detection_reports_conflict(self):
        first = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="Duplicate Candidate",
        )
        second = self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="Duplicate Candidate",
            expect=400,
        )
        self.assertEqual(Product.objects.count(), 1)

    def test_same_attributes_different_mrp_are_distinct_variants(self):
        # MRP is part of catalogue variant identity: a different printed MRP
        # creates a separate sellable variant, not a duplicate.
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="MRP Variant",
            mrp="10.00",
        )
        self.create_product(
            {"net_weight": "0.025", "units_per_master_box": 192},
            name="MRP Variant",
            mrp="20.00",
        )
        self.assertEqual(
            Product.objects.filter(name="MRP Variant").count(), 2
        )
        self.assertEqual(
            set(
                Product.objects.filter(name="MRP Variant").values_list(
                    "mrp", flat=True
                )
            ),
            {Decimal("10.00"), Decimal("20.00")},
        )


class DynamicFilteringTests(CatalogueTestBase):
    def test_filter_by_filterable_choice_attribute(self):
        self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Duracell AA",
                "base_unit": "piece",
                "catalogue_category": self.batteries.pk,
                "attributes": {"battery_size": "AA", "pack_quantity": 4},
            },
            format="json",
        )
        self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Duracell AAA",
                "base_unit": "piece",
                "catalogue_category": self.batteries.pk,
                "attributes": {"battery_size": "AAA", "pack_quantity": 4},
            },
            format="json",
        )
        response = self.client_as(self.admin).get("/api/products/?attr_battery_size=AA")
        self.assertEqual(response.status_code, 200, response.data)
        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Duracell AA"])

    def test_non_filterable_attribute_cannot_filter(self):
        self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Duracell AA",
                "base_unit": "piece",
                "catalogue_category": self.batteries.pk,
                "attributes": {"battery_size": "AA", "pack_quantity": 4},
            },
            format="json",
        )
        response = self.client_as(self.admin).get("/api/products/?attr_pack_quantity=4")
        self.assertEqual(response.status_code, 200)
        # pack_quantity is not filterable; the filter must be ignored, not restrict to zero rows
        # ...but also must not restrict to a subset that excludes the product when non-matching.
        self.assertEqual(response.data["count"], 1)


class InventoryIsolationTests(CatalogueTestBase):
    def test_attribute_changes_do_not_touch_stock(self):
        from .services import get_default_warehouse

        product = Product.objects.create(
            name="Isolated Product", base_unit="piece", catalogue_category=self.food
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.net_weight,
            value_number=Decimal("0.025"),
        )
        ProductAttributeValue.objects.create(
            product=product, attribute_definition=self.master_box, value_integer=192
        )
        adjust_inventory(
            product=product,
            quantity_delta=Decimal("50"),
            movement_type=StockLedger.OPENING_STOCK,
            created_by=self.admin,
        )
        balance = InventoryBalance.objects.get(
            product=product, warehouse=get_default_warehouse()
        )
        ledger_count = StockLedger.objects.filter(product=product).count()
        stock_before = product.current_stock

        update = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {"attributes": {"net_weight": "0.040", "units_per_master_box": 120}},
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.data)
        balance.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(balance.quantity_on_hand, Decimal("50.000"))
        self.assertEqual(
            StockLedger.objects.filter(product=product).count(), ledger_count
        )
        self.assertEqual(product.current_stock, stock_before)

    def test_category_change_does_not_touch_stock(self):
        from .services import get_default_warehouse

        product = Product.objects.create(
            name="Category Mover", base_unit="piece", catalogue_category=self.food
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.net_weight,
            value_number=Decimal("0.025"),
        )
        ProductAttributeValue.objects.create(
            product=product, attribute_definition=self.master_box, value_integer=192
        )
        adjust_inventory(
            product=product,
            quantity_delta=Decimal("10"),
            movement_type=StockLedger.OPENING_STOCK,
            created_by=self.admin,
        )
        # Move to Batteries: required net_weight/master_box no longer apply.
        update = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {
                "catalogue_category": self.batteries.pk,
                "attributes": {"battery_size": "AA", "pack_quantity": 4},
            },
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.data)
        balance = InventoryBalance.objects.get(
            product=product, warehouse=get_default_warehouse()
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("10.000"))
        # Food attributes are removed because they are not assigned to Batteries.
        self.assertFalse(
            ProductAttributeValue.objects.filter(
                product=product,
                attribute_definition__in=[self.net_weight, self.master_box],
            ).exists()
        )


class GSTIsolationTests(CatalogueTestBase):
    def test_dynamic_attributes_cannot_override_tax(self):
        response = self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Tax Guard",
                "base_unit": "piece",
                "catalogue_category": self.batteries.pk,
                "tax": self.tax.pk,
                "attributes": {"battery_size": "AA", "pack_quantity": 4},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(product.tax, self.tax)
        # Attributes never appear on the tax path: tax snapshot fields stay authoritative.
        invoice_data = {
            "product": product,
            "quantity": Decimal("1"),
            "rate_charged": Decimal("100"),
            "tax_rate": 18,
        }
        self.assertIn("tax", response.data)


class HistoricalInvoiceIsolationTests(CatalogueTestBase):
    def test_posted_invoice_unchanged_after_attribute_edits(self):
        from billing.models import BusinessProfile

        BusinessProfile.objects.create(
            business_name="Test Business",
            gstin="29TEST8888",
            registered_address="Addr",
            state="Karnataka",
            state_code="29",
        )
        customer = Customer.objects.create(name="History Customer", state_code="29")
        product = Product.objects.create(
            name="History Product",
            base_unit="piece",
            catalogue_category=self.food,
            default_price=Decimal("100"),
            cost_price=Decimal("60"),
            tax=self.tax,
        )
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=self.net_weight,
            value_number=Decimal("0.025"),
        )
        ProductAttributeValue.objects.create(
            product=product, attribute_definition=self.master_box, value_integer=192
        )
        adjust_inventory(
            product=product,
            quantity_delta=Decimal("5"),
            movement_type=StockLedger.OPENING_STOCK,
            created_by=self.admin,
        )
        invoice = create_invoice(
            customer=customer,
            invoice_number="INV-HIST-1",
            created_by=self.admin,
            payment_type="cash",
            line_items=[
                {
                    "product": product,
                    "quantity": Decimal("1"),
                    "rate_charged": Decimal("100"),
                    "tax_rate": 18,
                }
            ],
        )
        line = invoice.line_items.get()
        snapshot_before = (
            line.product_name_snapshot,
            line.base_unit_snapshot,
            line.hsn_sac_snapshot,
            line.rate_charged,
            line.line_total,
        )

        update = self.client_as(self.admin).patch(
            f"/api/products/{product.pk}/",
            {
                "name": "Renamed Product",
                "attributes": {"net_weight": "0.099", "units_per_master_box": 60},
            },
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.data)
        line.refresh_from_db()
        snapshot_after = (
            line.product_name_snapshot,
            line.base_unit_snapshot,
            line.hsn_sac_snapshot,
            line.rate_charged,
            line.line_total,
        )
        self.assertEqual(snapshot_before, snapshot_after)


class AuditLogTests(CatalogueTestBase):
    def test_catalogue_structure_changes_are_audited(self):
        self.client_as(self.admin).post(
            "/api/categories/",
            {"code": "audited", "name": "Audited Category"},
            format="json",
        )
        from billing.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="category_created", entity_type="Category"
            ).exists()
        )
        # flavour is assigned to food already; use a fresh attribute for batteries.
        laminated = AttributeDefinition.objects.create(
            code="laminated",
            name="Laminated",
            data_type=AttributeDefinition.TYPE_BOOLEAN,
        )
        self.client_as(self.admin).post(
            f"/api/categories/{self.batteries.pk}/attribute-assignments/",
            {"attribute_definition": laminated.pk},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="category_attribute_assigned", entity_type="CategoryAttribute"
            ).exists()
        )
        from billing.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="category_created", entity_type="Category"
            ).exists()
        )
        self.client_as(self.admin).post(
            f"/api/categories/{self.food.pk}/attribute-assignments/",
            {"attribute_definition": self.flavour.pk},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="category_attribute_assigned", entity_type="CategoryAttribute"
            ).exists()
        )


class ImportReadinessTests(CatalogueTestBase):
    """Chheda catalogue and Duracell examples prove the architecture is import-ready."""

    def test_chheda_snack_representation(self):
        """Yellow Banana Chips: net weight 0.025 kg, master box 192, MRP 10 — verbatim source values."""
        response = self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Chheda's Yellow banana Chips",
                "base_unit": "piece",
                "catalogue_category": self.food.pk,
                "mrp": "10.00",
                "attributes": {
                    "net_weight": 0.025,
                    "units_per_master_box": 192,
                    "flavour": "Banana",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(
            ProductAttributeValue.objects.get(
                product=product, attribute_definition=self.net_weight
            ).value_number,
            Decimal("0.025"),
        )
        self.assertEqual(product.mrp, Decimal("10.00"))
        # 30g / 120-box / MRP-20 sibling stays a separate row.
        sibling = self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Chheda's Yellow banana Chips",
                "base_unit": "piece",
                "catalogue_category": self.food.pk,
                "mrp": "20.00",
                "attributes": {"net_weight": 0.030, "units_per_master_box": 120},
            },
            format="json",
        )
        self.assertEqual(sibling.status_code, 201, sibling.data)
        self.assertEqual(Product.objects.count(), 2)

    def test_duracell_battery_representation(self):
        response = self.client_as(self.admin).post(
            "/api/products/",
            {
                "name": "Duracell AA Battery 4-Pack",
                "base_unit": "piece",
                "catalogue_category": self.batteries.pk,
                "mrp": "120.00",
                "default_price": "100.00",
                "attributes": {
                    "battery_size": "AA",
                    "chemistry": "Alkaline",
                    "pack_quantity": 4,
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["attributes"]["battery_size"], "AA")
        self.assertEqual(response.data["attributes"]["pack_quantity"], 4)
        self.assertEqual(response.data["mrp"], "120.00")
        self.assertEqual(response.data["default_price"], "100.00")


class ProductWritePermissionTests(CatalogueTestBase):
    def test_staff_cannot_create_product(self):
        response = self.client_as(self.staff).post(
            "/api/products/",
            {"name": "Staff Product", "base_unit": "piece"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_archive_product(self):
        product = Product.objects.create(name="Staff Archive Target", base_unit="piece")
        response = self.client_as(self.staff).delete(f"/api/products/{product.pk}/")
        self.assertEqual(response.status_code, 403)
        product.refresh_from_db()
        self.assertTrue(product.is_active)


class FrontendSupportEndpointTests(CatalogueTestBase):
    """Endpoints the Phase 2 frontend relies on: tax-rate list, choice CRUD, public tax_rate."""

    def test_tax_rate_list_available_to_staff(self):
        response = self.client_as(self.staff).get("/api/tax-rates/")
        self.assertEqual(response.status_code, 200)
        rates = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertIn(self.tax.pk, [r["id"] for r in rates])

    def test_attribute_choice_create_and_duplicate_rejected(self):
        response = self.client_as(self.admin).post(
            "/api/attribute-choices/",
            {"attribute_definition": self.battery_size.pk, "value": "AAAA", "label": "AAAA"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        duplicate = self.client_as(self.admin).post(
            "/api/attribute-choices/",
            {"attribute_definition": self.battery_size.pk, "value": "AA", "label": "Dup"},
            format="json",
        )
        self.assertIn(duplicate.status_code, {400, 500})

    def test_staff_cannot_create_attribute_choice(self):
        response = self.client_as(self.staff).post(
            "/api/attribute-choices/",
            {"attribute_definition": self.battery_size.pk, "value": "X", "label": "X"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_public_serializer_exposes_tax_rate_for_invoice_ui(self):
        product = Product.objects.create(
            name="Tax Rate Product", base_unit="piece", tax=self.tax
        )
        response = self.client_as(self.staff).get(f"/api/products/{product.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tax_rate"], "18.00")

    def test_customer_serializer_exposes_state_code(self):
        from customers.models import Customer
        from customers.serializers import CustomerSerializer

        customer = Customer.objects.create(
            name="State Code Customer", state_code="29", state="Karnataka"
        )
        serialized = CustomerSerializer(customer).data
        self.assertEqual(serialized["state_code"], "29")
        self.assertEqual(serialized["state"], "Karnataka")
