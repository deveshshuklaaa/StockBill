"""Authoritative tests for Selected Invoices Item-wise Summary endpoint.

POST /api/invoices/item-summary/

Rules tested:
1. Single selected invoice
2. Two selected invoices
3. Same product across multiple invoices
4. Different products across invoices
5. Master Box + Piece aggregation (summing base_quantity)
6. Base quantity is used, not displayed quantity
7. Multiple lines for same product within one invoice
8. Draft invoice excluded
9. Cancelled invoice excluded
10. Unauthorized invoice rejected (anonymous rejected with 401/403)
11. Duplicate invoice IDs handled safely
12. Empty selection rejected with 400
13. Product variants remain separate (Product.id grouping, not name)
14. Correct invoice count per product
15. Correct total base quantity
16. Database aggregation correctness (values, annotate, Sum, Count distinct)
"""

from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from customers.models import Customer
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    Supplier,
    TaxRate,
    Warehouse,
)
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse
from django.utils import timezone
from billing.services import create_invoice

User = get_user_model()


class InvoiceItemSummaryTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="summary-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="summary-staff", password="StrongPass123!", role="staff"
        )
        cls.unauthorized_user = User.objects.create_user(
            username="plain-user", password="StrongPass123!", role="customer"
        )

        BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            gstin="27DIVYA1234A1Z5",
            registered_address="Shop 1, Main Road, Mumbai",
            state="Maharashtra",
            state_code="27",
        )
        cls.tax, _ = TaxRate.objects.get_or_create(
            name="GST 18%", defaults={"rate": Decimal("18.00")}
        )
        cls.customer = Customer.objects.create(
            name="Summary Customer", state_code="27", credit_limit=Decimal("500000")
        )

        # Dynamic catalogue setup for attributes
        cls.category = Category.objects.create(name="Snacks", code="SNACKS")
        cls.attr_master_box = AttributeDefinition.objects.create(
            name="Units per Master Box",
            code="units_per_master_box",
            data_type=AttributeDefinition.TYPE_INTEGER,
        )
        cls.attr_net_weight = AttributeDefinition.objects.create(
            name="Net Weight",
            code="net_weight",
            data_type=AttributeDefinition.TYPE_DECIMAL,
        )
        CategoryAttribute.objects.create(
            category=cls.category, attribute_definition=cls.attr_master_box
        )
        CategoryAttribute.objects.create(
            category=cls.category, attribute_definition=cls.attr_net_weight
        )

        # Products:
        # Product 1: Yellow Banana Chips (has master box attribute = 192, net weight 0.025)
        cls.product_banana = Product.objects.create(
            name="Yellow Banana Chips",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            sku="YBC-25G",
            mrp=Decimal("10.00"),
            default_price=Decimal("10.00"),
            tax=cls.tax,
            catalogue_category=cls.category,
        )
        ProductAttributeValue.objects.create(
            product=cls.product_banana,
            attribute_definition=cls.attr_master_box,
            value_integer=192,
        )
        ProductAttributeValue.objects.create(
            product=cls.product_banana,
            attribute_definition=cls.attr_net_weight,
            value_number=Decimal("0.025"),
        )

        # Product 2: Classic Salted 25g (Variant A)
        cls.product_salted_25g = Product.objects.create(
            name="Classic Salted",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            sku="CS-25G",
            mrp=Decimal("10.00"),
            default_price=Decimal("10.00"),
            tax=cls.tax,
            catalogue_category=cls.category,
        )
        ProductAttributeValue.objects.create(
            product=cls.product_salted_25g,
            attribute_definition=cls.attr_net_weight,
            value_number=Decimal("0.025"),
        )

        # Product 3: Classic Salted 50g (Variant B - same name, different product_id/SKU/MRP)
        cls.product_salted_50g = Product.objects.create(
            name="Classic Salted",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            sku="CS-50G",
            mrp=Decimal("20.00"),
            default_price=Decimal("20.00"),
            tax=cls.tax,
            catalogue_category=cls.category,
        )
        ProductAttributeValue.objects.create(
            product=cls.product_salted_50g,
            attribute_definition=cls.attr_net_weight,
            value_number=Decimal("0.050"),
        )

        # Product 4: Manglori Mix
        cls.product_manglori = Product.objects.create(
            name="Manglori Mix",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            sku="MM-25G",
            mrp=Decimal("10.00"),
            default_price=Decimal("10.00"),
            tax=cls.tax,
        )

        # Product 5: Tasty Nuts
        cls.product_nuts = Product.objects.create(
            name="Tasty Nuts",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            sku="TN-20G",
            mrp=Decimal("10.00"),
            default_price=Decimal("10.00"),
            tax=cls.tax,
        )

        cls.supplier = Supplier.objects.create(
            name="Summary Supplier", gstin="27SUPPL1234A1Z5", state="Maharashtra", state_code="27"
        )
        cls.warehouse = get_default_warehouse()
        create_purchase(
            supplier=cls.supplier,
            warehouse=cls.warehouse,
            invoice_date=timezone.localdate(),
            line_items=[
                {"product": cls.product_banana, "quantity": Decimal("1000"), "rate": Decimal("5.00")},
                {"product": cls.product_salted_25g, "quantity": Decimal("1000"), "rate": Decimal("5.00")},
                {"product": cls.product_salted_50g, "quantity": Decimal("1000"), "rate": Decimal("10.00")},
                {"product": cls.product_manglori, "quantity": Decimal("1000"), "rate": Decimal("5.00")},
                {"product": cls.product_nuts, "quantity": Decimal("1000"), "rate": Decimal("5.00")},
            ],
            created_by=cls.admin,
            post=True,
        )

        # Create test invoices:
        # Invoice 1 (POSTED):
        # - Yellow Banana Chips: 4 pcs
        # - Classic Salted 25g: 3 pcs
        # - Manglori Mix: 15 pcs
        cls.inv_1 = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-001",
            created_by=cls.admin,
            payment_type="credit",
            line_items=[
                {"product": cls.product_banana, "quantity": Decimal("4"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
                {"product": cls.product_salted_25g, "quantity": Decimal("3"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
                {"product": cls.product_manglori, "quantity": Decimal("15"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
            ],
        )

        # Invoice 2 (POSTED):
        # - Tasty Nuts: 4 pcs
        # - Classic Salted 25g: 35 pcs
        # - Yellow Banana Chips: 12 pcs
        cls.inv_2 = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-002",
            created_by=cls.admin,
            payment_type="credit",
            line_items=[
                {"product": cls.product_nuts, "quantity": Decimal("4"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
                {"product": cls.product_salted_25g, "quantity": Decimal("35"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
                {"product": cls.product_banana, "quantity": Decimal("12"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
            ],
        )

        # Invoice 3 (POSTED) with Master Box and Variant 50g:
        # - Yellow Banana Chips in Master Box: 2 boxes (conversion_factor=192 -> 384 base pcs)
        # - Classic Salted 50g: 10 pcs
        cls.inv_3_box = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-003",
            created_by=cls.admin,
            payment_type="credit",
            line_items=[
                {
                    "product": cls.product_banana,
                    "sales_unit_name": "master box",
                    "quantity": Decimal("2"),
                    "conversion_factor": Decimal("192"),
                    "rate_charged": Decimal("10.00"),
                    "tax_rate": Decimal("18.00"),
                },
                {
                    "product": cls.product_salted_50g,
                    "quantity": Decimal("10"),
                    "rate_charged": Decimal("20.00"),
                    "tax_rate": Decimal("18.00"),
                },
            ],
        )

        # Invoice 4 (POSTED) with multiple lines for the same product:
        # - Tasty Nuts: 6 pcs
        # - Tasty Nuts: 14 pcs (e.g. promo or separate batch)
        cls.inv_4_multi = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-004",
            created_by=cls.admin,
            payment_type="credit",
            line_items=[
                {"product": cls.product_nuts, "quantity": Decimal("6"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
                {"product": cls.product_nuts, "quantity": Decimal("14"), "rate_charged": Decimal("9.50"), "tax_rate": Decimal("18.00")},
            ],
        )

        # Invoice 5 (DRAFT):
        # - Yellow Banana Chips: 100 pcs (MUST NOT contribute)
        cls.inv_draft = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-DRAFT-005",
            created_by=cls.admin,
            payment_type="credit",
            state=Invoice.STATE_DRAFT,
            line_items=[
                {"product": cls.product_banana, "quantity": Decimal("100"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
            ],
        )

        # Invoice 6 (CANCELLED):
        # - Yellow Banana Chips: 50 pcs (MUST NOT contribute)
        cls.inv_cancelled = create_invoice(
            customer=cls.customer,
            invoice_number="INV-SUM-CANCEL-006",
            created_by=cls.admin,
            payment_type="credit",
            line_items=[
                {"product": cls.product_banana, "quantity": Decimal("50"), "rate_charged": Decimal("10.00"), "tax_rate": Decimal("18.00")},
            ],
        )
        cls.inv_cancelled.state = Invoice.STATE_CANCELLED
        cls.inv_cancelled._allow_lifecycle_transition = True
        cls.inv_cancelled.save()

    def client_as(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def test_single_selected_invoice(self):
        """1. Single selected invoice summary works correctly."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 1)
        self.assertEqual(data["invoice_numbers"], ["INV-SUM-001"])
        self.assertEqual(data["total_products"], 3)
        self.assertEqual(Decimal(data["total_base_quantity"]), Decimal("22.000"))

        item_map = {item["product_id"]: item for item in data["items"]}
        self.assertEqual(Decimal(item_map[self.product_banana.id]["total_base_quantity"]), Decimal("4.000"))
        self.assertEqual(item_map[self.product_banana.id]["invoice_count"], 1)
        self.assertEqual(Decimal(item_map[self.product_salted_25g.id]["total_base_quantity"]), Decimal("3.000"))
        self.assertEqual(Decimal(item_map[self.product_manglori.id]["total_base_quantity"]), Decimal("15.000"))

    def test_two_selected_invoices(self):
        """2 & 3 & 4. Two selected invoices (Example from prompt):
        Banana Chips: 4 + 12 = 16 pcs
        Classic Salted: 3 + 35 = 38 pcs
        Manglori Mix: 15 pcs
        Tasty Nuts: 4 pcs
        Total = 73 pcs
        """
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_2.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 2)
        self.assertEqual(set(data["invoice_numbers"]), {"INV-SUM-001", "INV-SUM-002"})
        self.assertEqual(data["total_products"], 4)
        self.assertEqual(Decimal(data["total_base_quantity"]), Decimal("73.000"))

        item_map = {item["product_id"]: item for item in data["items"]}
        self.assertEqual(Decimal(item_map[self.product_banana.id]["total_base_quantity"]), Decimal("16.000"))
        self.assertEqual(item_map[self.product_banana.id]["invoice_count"], 2)

        self.assertEqual(Decimal(item_map[self.product_salted_25g.id]["total_base_quantity"]), Decimal("38.000"))
        self.assertEqual(item_map[self.product_salted_25g.id]["invoice_count"], 2)

        self.assertEqual(Decimal(item_map[self.product_manglori.id]["total_base_quantity"]), Decimal("15.000"))
        self.assertEqual(item_map[self.product_manglori.id]["invoice_count"], 1)

        self.assertEqual(Decimal(item_map[self.product_nuts.id]["total_base_quantity"]), Decimal("4.000"))
        self.assertEqual(item_map[self.product_nuts.id]["invoice_count"], 1)

    def test_master_box_and_piece_aggregation(self):
        """5 & 6. Master Box + Piece sums base_quantity, NOT displayed quantity.
        Invoice 1: 4 pcs Banana Chips
        Invoice 3: 2 Master Boxes x 192 = 384 pcs Banana Chips
        Total Banana Chips = 388 pcs (NOT 4 + 2 = 6).
        """
        client = self.client_as(self.admin)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_3_box.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        item_map = {item["product_id"]: item for item in data["items"]}
        banana_item = item_map[self.product_banana.id]
        self.assertEqual(Decimal(banana_item["total_base_quantity"]), Decimal("388.000"))
        self.assertEqual(banana_item["invoice_count"], 2)

    def test_multiple_lines_for_same_product_in_one_invoice(self):
        """7. Multiple line items for the same product in a single invoice are summed."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_4_multi.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 1)
        self.assertEqual(data["total_products"], 1)
        nuts_item = data["items"][0]
        # 6 + 14 = 20 pcs
        self.assertEqual(Decimal(nuts_item["total_base_quantity"]), Decimal("20.000"))
        # Only 1 invoice contains this product
        self.assertEqual(nuts_item["invoice_count"], 1)

    def test_draft_invoice_excluded(self):
        """8. Draft invoice is excluded from the summary."""
        client = self.client_as(self.staff)
        # Select inv_1 (4 pcs Banana Chips) and inv_draft (100 pcs Banana Chips)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_draft.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        # Only inv_1 should be counted
        self.assertEqual(data["invoice_count"], 1)
        self.assertEqual(data["invoice_numbers"], ["INV-SUM-001"])
        item_map = {item["product_id"]: item for item in data["items"]}
        # Banana chips should be 4 pcs, NOT 104 pcs
        self.assertEqual(Decimal(item_map[self.product_banana.id]["total_base_quantity"]), Decimal("4.000"))

    def test_cancelled_invoice_excluded(self):
        """9. Cancelled invoice is excluded from the summary."""
        client = self.client_as(self.staff)
        # Select inv_1 (4 pcs Banana Chips) and inv_cancelled (50 pcs Banana Chips)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_cancelled.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 1)
        self.assertEqual(data["invoice_numbers"], ["INV-SUM-001"])
        item_map = {item["product_id"]: item for item in data["items"]}
        # Banana chips should be 4 pcs, NOT 54 pcs
        self.assertEqual(Decimal(item_map[self.product_banana.id]["total_base_quantity"]), Decimal("4.000"))

    def test_unauthorized_invoice_rejected(self):
        """10. Unauthenticated or unauthorized access is rejected."""
        anonymous = self.client_as(None)
        res = anonymous.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id]},
            format="json",
        )
        self.assertIn(res.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

        # Non-staff role
        unauth_client = self.client_as(self.unauthorized_user)
        res_unauth = unauth_client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id]},
            format="json",
        )
        self.assertEqual(res_unauth.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_invoice_ids_handled(self):
        """11. Duplicate invoice IDs in request are safely deduplicated."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_1.id, self.inv_2.id, self.inv_2.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 2)
        # Quantities must not be doubled: Banana Chips = 16, Total = 73
        self.assertEqual(Decimal(data["total_base_quantity"]), Decimal("73.000"))

    def test_empty_selection_rejected(self):
        """12. Empty selection is rejected with 400 Bad Request."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": []},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invoice_ids", res.data)

        # Missing field
        res_missing = client.post("/api/invoices/item-summary/", {}, format="json")
        self.assertEqual(res_missing.status_code, status.HTTP_400_BAD_REQUEST)

    def test_product_variants_remain_separate(self):
        """13. Variants with same name (Classic Salted 25g vs 50g) remain separate by Product.id."""
        client = self.client_as(self.staff)
        # inv_1 has Classic Salted 25g (3 pcs)
        # inv_3_box has Classic Salted 50g (10 pcs)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_3_box.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        item_ids = [item["product_id"] for item in data["items"]]
        self.assertIn(self.product_salted_25g.id, item_ids)
        self.assertIn(self.product_salted_50g.id, item_ids)

        item_map = {item["product_id"]: item for item in data["items"]}
        var_25 = item_map[self.product_salted_25g.id]
        var_50 = item_map[self.product_salted_50g.id]

        self.assertEqual(Decimal(var_25["total_base_quantity"]), Decimal("3.000"))
        self.assertEqual(Decimal(var_50["total_base_quantity"]), Decimal("10.000"))
        self.assertEqual(var_25["sku"], "CS-25G")
        self.assertEqual(var_50["sku"], "CS-50G")

    def test_invoice_count_per_product(self):
        """14. Correct invoice count per product reflects how many selected invoices contain it."""
        client = self.client_as(self.staff)
        # Invoices 1 and 2:
        # Banana chips is in both (count = 2)
        # Manglori is only in inv 1 (count = 1)
        # Nuts is only in inv 2 (count = 1)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_2.id]},
            format="json",
        )
        data = res.data
        item_map = {item["product_id"]: item for item in data["items"]}
        self.assertEqual(item_map[self.product_banana.id]["invoice_count"], 2)
        self.assertEqual(item_map[self.product_manglori.id]["invoice_count"], 1)
        self.assertEqual(item_map[self.product_nuts.id]["invoice_count"], 1)

    def test_only_draft_or_cancelled_selected_returns_clean_empty(self):
        """Gracefully returns empty list if only draft or cancelled invoices were sent."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_draft.id, self.inv_cancelled.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["invoice_count"], 0)
        self.assertEqual(data["total_products"], 0)
        self.assertEqual(data["items"], [])
        self.assertEqual(Decimal(data["total_base_quantity"]), Decimal("0.000"))

    def test_same_product_across_multiple_invoices(self):
        """3. Same product repeated across multiple invoices sums correctly."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_2.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        item_map = {item["product_id"]: item for item in res.data["items"]}
        # Banana Chips appears in Inv 1 (4 pcs) and Inv 2 (12 pcs) -> 16 pcs
        self.assertEqual(Decimal(item_map[self.product_banana.id]["total_base_quantity"]), Decimal("16.000"))
        # Classic Salted 25g appears in Inv 1 (3 pcs) and Inv 2 (35 pcs) -> 38 pcs
        self.assertEqual(Decimal(item_map[self.product_salted_25g.id]["total_base_quantity"]), Decimal("38.000"))

    def test_different_products_across_invoices(self):
        """4. Different products across invoices are all included in summary."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_2.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Inv 1 has Banana, Salted 25g, Manglori. Inv 2 has Banana, Salted 25g, Nuts.
        product_names = {item["product_name"] for item in res.data["items"]}
        self.assertEqual(product_names, {"Yellow Banana Chips", "Classic Salted", "Manglori Mix", "Tasty Nuts"})

    def test_base_quantity_used_not_displayed_quantity(self):
        """6. System must never calculate 2 boxes + 4 pcs = 6; it must calculate 384 + 4 = 388 pcs."""
        client = self.client_as(self.admin)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_3_box.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        item_map = {item["product_id"]: item for item in res.data["items"]}
        banana_item = item_map[self.product_banana.id]
        # Never 6! Must be 388 pcs.
        self.assertNotEqual(Decimal(banana_item["total_base_quantity"]), Decimal("6.000"))
        self.assertEqual(Decimal(banana_item["total_base_quantity"]), Decimal("388.000"))

    def test_correct_total_base_quantity(self):
        """15. Correct overall grand total base quantity across all products."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id, self.inv_2.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Sum of items: 16 (Banana) + 38 (Salted) + 15 (Manglori) + 4 (Nuts) = 73
        self.assertEqual(Decimal(res.data["total_base_quantity"]), Decimal("73.000"))

    def test_database_aggregation_correctness(self):
        """16. Database aggregation produces correct fields and formats."""
        client = self.client_as(self.staff)
        res = client.post(
            "/api/invoices/item-summary/",
            {"invoice_ids": [self.inv_1.id]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        for item in data["items"]:
            self.assertIn("product_id", item)
            self.assertIn("product_name", item)
            self.assertIn("sku", item)
            self.assertIn("mrp", item)
            self.assertIn("total_base_quantity", item)
            self.assertIn("invoice_count", item)
            self.assertIn("variant_summary", item)
            self.assertIn("attributes", item)

