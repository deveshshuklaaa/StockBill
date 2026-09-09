"""Pagination and server-side search/filter tests for the Product list API.

Uses the real 109-row Chheda catalogue importer to reproduce the production
data shape, then proves:
- paged access reaches every product (25/25/25/25/9 across 5 pages)
- pagination metadata (count/next/previous) is correct
- search hits products beyond page 1
- category/status/dynamic-attribute filters apply server-side
- filters combine with search and pagination
- staff retain read access to paginated results
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from io import StringIO
from rest_framework.test import APITestCase

from .models import Category, CategoryAttribute, Product, ProductAttributeValue, Supplier

User = get_user_model()

SPECIALITIES = "Chheda Specialities Foods Pvt. Ltd."
AGRO_PARK = "Chheda Agro Food Park Private Ltd."


def import_catalogue():
    out = StringIO()
    call_command("import_chheda_catalogue", stdout=out)


class ProductPaginationTestBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="page-admin", password="StrongPass123!", role="admin"
        )
        self.staff = User.objects.create_user(
            username="page-staff", password="StrongPass123!", role="staff"
        )
        import_catalogue()

    def client_as(self, user):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user)
        return client

    def get(self, query="", user=None):
        response = (self.client_as(user or self.admin)).get(f"/api/products/{query}")
        self.assertEqual(response.status_code, 200, response.data)
        return response


class ProductPaginationTests(ProductPaginationTestBase):
    def test_page_1_returns_25_products_with_total_count_109(self):
        response = self.get()
        self.assertEqual(response.data["count"], 109)
        self.assertEqual(len(response.data["results"]), 25)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_all_pages_together_contain_all_109_products(self):
        seen = []
        page = 1
        while True:
            response = self.get(f"?page={page}")
            seen.extend(row["id"] for row in response.data["results"])
            if response.data["next"] is None:
                break
            page += 1
        self.assertEqual(len(seen), 109)
        self.assertEqual(len(set(seen)), 109)  # no duplicates across pages

    def test_page_sizes_are_25_25_25_25_9(self):
        sizes = []
        for page in range(1, 6):
            response = self.get(f"?page={page}")
            sizes.append(len(response.data["results"]))
        self.assertEqual(sizes, [25, 25, 25, 25, 9])

    def test_page_2_metadata_links_neighbours(self):
        response = self.get("?page=2")
        self.assertEqual(response.data["count"], 109)
        self.assertIn("page=3", response.data["next"])
        # DRF omits the redundant page=1 query param (page 1 is the default).
        self.assertIsNotNone(response.data["previous"])
        self.assertEqual(response.data["previous"].split("?")[0].rstrip("/"), "http://testserver/api/products")
        self.assertNotIn("page=2", response.data["previous"])

    def test_final_page_has_no_next(self):
        response = self.get("?page=5")
        self.assertEqual(len(response.data["results"]), 9)
        self.assertIsNone(response.data["next"])
        self.assertIsNotNone(response.data["previous"])

    def test_ordering_is_stable_across_pages(self):
        page1 = [row["name"] for row in self.get().data["results"]]
        page2 = [row["name"] for row in self.get("?page=2").data["results"]]
        self.assertEqual(page1, sorted(page1))
        self.assertTrue(page1[-1] < page2[0])


class ProductServerSearchTests(ProductPaginationTestBase):
    def test_search_finds_products_outside_page_1(self):
        # "Rajgeera Bar" sorts well past page 1 alphabetically; a client-side
        # search over page 1 would never find it.
        for name in [
            "Chheda's Rajgeera Bar",
            "Udupi Munch Masala Murukku",
            "Potato Corn Stix Cream-n-Onion 52g",
        ]:
            response = self.get(f"?search={name}")
            self.assertEqual(response.data["count"], 1, name)
            self.assertEqual(response.data["results"][0]["name"], name)

    def test_search_matches_partial_names_across_catalogue(self):
        response = self.get("?search=banana")
        names = {row["name"] for row in response.data["results"]}
        self.assertTrue(names)
        for name in names:
            self.assertIn("banana", name.lower())
        # All banana products across all pages
        expected = Product.objects.filter(name__icontains="banana").count()
        self.assertEqual(response.data["count"], expected)

    def test_search_is_case_insensitive(self):
        response = self.get("?search=MURUKKU")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["name"], "Udupi Munch Masala Murukku"
        )

    def test_search_matches_sku_and_brand(self):
        product = Product.objects.first()
        product.sku = "ZZ-FOUND-BY-SKU"
        product.brand = "Chheda"
        product.save(update_fields=["sku", "brand", "updated_at"])
        response = self.get("?search=ZZ-FOUND-BY-SKU")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], product.id)

    def test_search_with_no_matches_returns_empty_page_not_error(self):
        response = self.get("?search=doesnotexist")
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["next"])


class ProductServerFilterTests(ProductPaginationTestBase):
    def test_category_filter_covers_full_catalogue(self):
        category = Category.objects.get(code="packaged-food")
        response = self.get(f"?category={category.pk}")
        self.assertEqual(response.data["count"], 109)
        for row in response.data["results"]:
            self.assertEqual(row["catalogue_category"], category.pk)

    def test_category_filter_excludes_other_categories(self):
        other = Category.objects.create(code="other", name="Other Goods")
        Product.objects.create(
            name="Non Catalogue Item",
            base_unit="piece",
            catalogue_category=other,
        )
        response = self.get(f"?category={other.pk}")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Non Catalogue Item")

    def test_category_filter_invalid_rejected(self):
        response = self.client_as(self.admin).get(
            "/api/products/?category=notanumber"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("category", response.data)

    def test_status_filter_active_across_catalogue(self):
        # Archive a few products so both buckets are populated.
        for product in Product.objects.all()[:5]:
            product.is_active = False
            product.save(update_fields=["is_active", "updated_at"])
        active_response = self.get("?is_active=true")
        self.assertEqual(active_response.data["count"], 104)
        archived_response = self.get("?is_active=false")
        self.assertEqual(archived_response.data["count"], 5)
        for row in archived_response.data["results"]:
            self.assertFalse(row["is_active"])

    def test_status_filter_invalid_rejected(self):
        response = self.client_as(self.admin).get("/api/products/?is_active=maybe")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("is_active", response.data)

    def test_search_and_category_combine(self):
        category = Category.objects.get(code="packaged-food")
        other = Category.objects.create(code="other", name="Other Goods")
        Product.objects.create(
            name="Banana Craft Item",
            base_unit="piece",
            catalogue_category=other,
        )
        response = self.get(f"?search=banana&category={category.pk}")
        self.assertGreater(response.data["count"], 0)
        for row in response.data["results"]:
            self.assertIn("banana", row["name"].lower())
            self.assertEqual(row["catalogue_category"], category.pk)
        # The out-of-category banana item must not leak into results.
        names = {row["name"] for row in response.data["results"]}
        self.assertNotIn("Banana Craft Item", names)

    def test_search_and_status_combine(self):
        for product in Product.objects.filter(name__icontains="banana")[:3]:
            product.is_active = False
            product.save(update_fields=["is_active", "updated_at"])
        response = self.get("?search=banana&is_active=false")
        self.assertEqual(response.data["count"], 3)
        for row in response.data["results"]:
            self.assertFalse(row["is_active"])
            self.assertIn("banana", row["name"].lower())

    def test_filtered_results_paginate(self):
        # 41 products match "chips"; verify they flow across two pages.
        response = self.get("?search=chips")
        total = response.data["count"]
        self.assertGreater(total, 25)
        seen = len(response.data["results"])
        page = 2
        while response.data["next"] is not None:
            response = self.get(f"?search=chips&page={page}")
            seen += len(response.data["results"])
            page += 1
        self.assertEqual(seen, total)


class ProductPaginationPermissionTests(ProductPaginationTestBase):
    def test_staff_can_read_paginated_results_without_cost_price(self):
        response = self.get(user=self.staff)
        self.assertEqual(response.data["count"], 109)
        self.assertEqual(len(response.data["results"]), 25)
        for row in response.data["results"]:
            self.assertNotIn("cost_price", row)

    def test_staff_search_reaches_late_pages(self):
        response = self.get("?search=Murukku", user=self.staff)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["name"], "Udupi Munch Masala Murukku"
        )

    def test_admin_retains_management_permissions(self):
        client = self.client_as(self.admin)
        created = client.post(
            "/api/products/",
            {
                "name": "Admin Managed Product",
                "base_unit": "piece",
                "catalogue_category": Category.objects.get(
                    code="packaged-food"
                ).pk,
                "mrp": "5.00",
                "attributes": {"net_weight": "0.014", "units_per_master_box": 240},
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

    def test_staff_cannot_create_products(self):
        client = self.client_as(self.staff)
        created = client.post(
            "/api/products/",
            {"name": "Staff Product", "base_unit": "piece"},
            format="json",
        )
        self.assertEqual(created.status_code, 403)

    def test_authentication_still_required(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/products/")
        self.assertIn(response.status_code, {401, 403})


class DynamicAttributeFilterWithPaginationTests(ProductPaginationTestBase):
    """Dynamic attr_* filters must keep working alongside search/filters."""

    def setUp(self):
        super().setUp()
        # The importer leaves filterability off; flag net_weight filterable
        # (test-local setup, mirrors the batteries tests' filterable flag)
        # so attr_net_weight filtering can be exercised against real rows.
        assignment = CategoryAttribute.objects.get(
            category__code="packaged-food",
            attribute_definition__code="net_weight",
        )
        assignment.is_filterable = True
        assignment.save(update_fields=["is_filterable"])

    def test_dynamic_attribute_filter_across_catalogue(self):
        # net_weight is flagged filterable for packaged-food in the catalogue
        # structure; 0.025 kg appears in rows 15, 23 and 30.
        response = self.get("?attr_net_weight=0.025")
        names = sorted(row["name"] for row in response.data["results"])
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(
            names,
            [
                "Chheda's Choco Vanilla Snax",
                "Chheda's Yellow Banana Chips",
                "Minilo Vanilla Mawa Cake",
            ],
        )

    def test_dynamic_filter_and_search_combine(self):
        response = self.get("?search=banana&attr_net_weight=0.025")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["name"], "Chheda's Yellow Banana Chips"
        )
        self.assertEqual(
            ProductAttributeValue.objects.get(
                product=response.data["results"][0]["id"],
                attribute_definition__code="net_weight",
            ).value_number,
            Decimal("0.025"),
        )
