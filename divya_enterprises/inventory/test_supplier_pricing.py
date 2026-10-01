from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.test import APITestCase

from billing.models import AuditLog, BusinessProfile
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    PurchaseInvoice,
    PurchaseLineItem,
    Supplier,
    SupplierPurchasePricing,
    TaxRate,
)
from inventory.purchase_services import create_purchase, post_purchase
from inventory.services import ensure_inventory_balance, get_default_warehouse

User = get_user_model()


class SupplierPurchasePricingTests(APITestCase):
    """Comprehensive test suite for Supplier MRP-based Purchase Pricing."""

    def setUp(self):
        super().setUp()
        self.warehouse = get_default_warehouse()

        self.admin = User.objects.create_user(
            username="supp_pricing_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="supp_pricing_staff", password="password", role=User.ROLE_STAFF
        )

        self.business_profile = BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            trade_name="Divya FMCG",
            gstin="27ECNPS6389P1Z5",
            registered_address="Mumbai",
            state="Maharashtra",
            state_code="27",
        )

        self.tax_5, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})

        # Category and Master Box attribute
        self.category = Category.objects.create(code="SNK_SUPP", name="Snacks Supplier Test")
        self.mb_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.get_or_create(
            category=self.category, attribute_definition=self.mb_attr
        )

        # Suppliers
        self.supp_a = Supplier.objects.create(
            name="Chheda Agro Food Park Pvt. Ltd.",
            state="Maharashtra",
            state_code="27",
            is_active=True,
        )
        self.supp_b = Supplier.objects.create(
            name="National Trading Co.",
            state="Maharashtra",
            state_code="27",
            is_active=True,
        )

        # Products with various MRPs
        # MRP ₹5 products
        self.prod_a5 = Product.objects.create(
            name="Chheda Banana Chips 20g",
            brand="Chheda",
            sku="BAN-20G",
            mrp=Decimal("5.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_a5, warehouse=self.warehouse)

        self.prod_b5 = Product.objects.create(
            name="Chheda Masala Sev 20g",
            brand="Chheda",
            sku="SEV-20G",
            mrp=Decimal("5.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_b5, warehouse=self.warehouse)

        self.prod_c5 = Product.objects.create(
            name="Chheda Bhelpuri 20g",
            brand="Chheda",
            sku="BHEL-20G",
            mrp=Decimal("5.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_c5, warehouse=self.warehouse)

        # MRP ₹10 products
        self.prod_d10 = Product.objects.create(
            name="Chheda Mix 100g",
            brand="Chheda",
            sku="MIX-100",
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_d10, warehouse=self.warehouse)

        self.prod_e10 = Product.objects.create(
            name="Chheda Poha 200g",
            brand="Chheda",
            sku="POHA-200",
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_e10, warehouse=self.warehouse)

        # MRP ₹20 product
        self.prod_f20 = Product.objects.create(
            name="Chheda Special Farsan 400g",
            brand="Chheda",
            sku="FARSAN-400",
            mrp=Decimal("20.00"),
            tax=self.tax_5,
            current_stock=Decimal("100.000"),
            is_active=True,
        )
        ensure_inventory_balance(product=self.prod_f20, warehouse=self.warehouse)

        # Master Box product: MRP ₹10, 24 units/master box
        self.prod_mb = Product.objects.create(
            name="Chheda Farsan Box",
            brand="Chheda",
            sku="FARSAN-MB",
            catalogue_category=self.category,
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("200.000"),
            is_active=True,
        )
        ProductAttributeValue.objects.create(
            product=self.prod_mb, attribute_definition=self.mb_attr, value_integer=24
        )
        ensure_inventory_balance(product=self.prod_mb, warehouse=self.warehouse)

    def test_create_and_retrieve_supplier_mrp_pricing(self):
        """1. Supplier + MRP pricing can be created and retrieved."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.20"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["mrp"]), Decimal("5.00"))
        self.assertEqual(Decimal(res.data["rate_per_piece"]), Decimal("3.20"))
        self.assertEqual(res.data["supplier_name"], self.supp_a.name)

        # Audit log verified
        self.assertTrue(
            AuditLog.objects.filter(
                action="supplier_purchase_pricing_created",
                entity_type="SupplierPurchasePricing",
            ).exists()
        )

        # Fetch supplier pricing list
        list_res = self.client.get(f"/api/suppliers/{self.supp_a.id}/pricing/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_res.data["pricing"]), 1)
        item = list_res.data["pricing"][0]
        self.assertEqual(Decimal(item["mrp"]), Decimal("5.00"))
        self.assertEqual(Decimal(item["rate_per_piece"]), Decimal("3.20"))
        # Catalogue MRPs available
        self.assertIn("5.00", [str(m) for m in list_res.data["available_mrps"]])

    def test_duplicate_supplier_mrp_is_rejected_or_updates(self):
        """2. Duplicate supplier + MRP is rejected at DB constraint and updates via endpoint."""
        # Endpoint updates on duplicate POST
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.20"},
            format="json",
        )
        res2 = self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.25"},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(SupplierPurchasePricing.objects.filter(supplier=self.supp_a, mrp=Decimal("5.00")).count(), 1)
        self.assertEqual(
            SupplierPurchasePricing.objects.get(supplier=self.supp_a, mrp=Decimal("5.00")).rate_per_piece,
            Decimal("3.25"),
        )

        # Direct DB creation with duplicate (supplier, mrp) raises IntegrityError
        with self.assertRaises(IntegrityError):
            SupplierPurchasePricing.objects.create(
                supplier=self.supp_a,
                mrp=Decimal("5.00"),
                rate_per_piece=Decimal("4.00"),
            )

    def test_different_suppliers_can_have_different_rates_for_same_mrp(self):
        """3. Different suppliers can have different rates for the same MRP."""
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.20"},
            format="json",
        )
        self.client.post(
            f"/api/suppliers/{self.supp_b.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.45"},
            format="json",
        )

        pricing_a = SupplierPurchasePricing.objects.get(supplier=self.supp_a, mrp=Decimal("5.00"))
        pricing_b = SupplierPurchasePricing.objects.get(supplier=self.supp_b, mrp=Decimal("5.00"))
        self.assertEqual(pricing_a.rate_per_piece, Decimal("3.20"))
        self.assertEqual(pricing_b.rate_per_piece, Decimal("3.45"))

    def test_same_supplier_different_rates_for_different_mrp_slabs(self):
        """4. Same supplier can have different rates for different MRP slabs."""
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.20"},
            format="json",
        )
        self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "10.00", "rate_per_piece": "6.40"},
            format="json",
        )
        self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "20.00", "rate_per_piece": "12.80"},
            format="json",
        )

        res = self.client.get(f"/api/suppliers/{self.supp_a.id}/pricing/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        rates_by_mrp = {Decimal(p["mrp"]): Decimal(p["rate_per_piece"]) for p in res.data["pricing"]}
        self.assertEqual(rates_by_mrp[Decimal("5.00")], Decimal("3.20"))
        self.assertEqual(rates_by_mrp[Decimal("10.00")], Decimal("6.40"))
        self.assertEqual(rates_by_mrp[Decimal("20.00")], Decimal("12.80"))

    def test_multiple_products_with_same_mrp_all_receive_same_supplier_rate(self):
        """5. Multiple products with the same MRP all receive the same supplier rate."""
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )

        # Products A, B, C all have MRP ₹5.00
        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[
                {"product": self.prod_a5, "quantity": Decimal("10"), "rate": None},
                {"product": self.prod_b5, "quantity": Decimal("20"), "rate": None},
                {"product": self.prod_c5, "quantity": Decimal("30"), "rate": None},
            ],
            created_by=self.admin,
        )

        lines = purchase.line_items.all().order_by("product__name")
        self.assertEqual(lines.count(), 3)
        for line in lines:
            self.assertEqual(line.rate, Decimal("3.20"))

    def test_products_with_different_mrp_receive_corresponding_rates(self):
        """6. Products with different MRP values receive their corresponding rates."""
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("10.00"),
            rate_per_piece=Decimal("6.40"),
        )

        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[
                {"product": self.prod_a5, "quantity": Decimal("10"), "rate": None},  # MRP 5 -> 3.20
                {"product": self.prod_d10, "quantity": Decimal("10"), "rate": None}, # MRP 10 -> 6.40
            ],
            created_by=self.admin,
        )

        line_a = purchase.line_items.get(product=self.prod_a5)
        line_d = purchase.line_items.get(product=self.prod_d10)
        self.assertEqual(line_a.rate, Decimal("3.20"))
        self.assertEqual(line_d.rate, Decimal("6.40"))

    def test_purchase_entry_autofills_correct_rate_based_on_product_mrp(self):
        """7. Purchase entry auto-fills the correct rate based on product MRP."""
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )

        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[{"product": self.prod_a5, "quantity": Decimal("5"), "rate": None}],
            created_by=self.admin,
        )
        line = purchase.line_items.first()
        self.assertEqual(line.rate, Decimal("3.20"))
        # 5 * 3.20 = 16.00 gross
        self.assertEqual(line.taxable_value, Decimal("16.00"))

    def test_missing_supplier_mrp_pricing_allows_manual_rate_entry(self):
        """8. Missing supplier+MRP pricing allows manual rate entry, and rejects empty rate."""
        # Product with MRP 20 has no pricing configured for Supplier A
        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[{"product": self.prod_f20, "quantity": Decimal("5"), "rate": Decimal("14.50")}],
            created_by=self.admin,
        )
        line = purchase.line_items.first()
        self.assertEqual(line.rate, Decimal("14.50"))

        # If no rate is passed and no supplier pricing exists for that MRP, ValidationError is raised
        with self.assertRaises(serializers.ValidationError) as ctx:
            create_purchase(
                supplier=self.supp_a,
                warehouse=self.warehouse,
                invoice_date=timezone.now().date(),
                line_items=[{"product": self.prod_f20, "quantity": Decimal("5"), "rate": None}],
                created_by=self.admin,
            )
        self.assertIn("Purchase rate is required", str(ctx.exception))

    def test_manual_override_does_not_modify_master_pricing(self):
        """9. User can override the default rate on a purchase line without modifying master pricing."""
        master = SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )

        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[
                {"product": self.prod_a5, "quantity": Decimal("10"), "rate": Decimal("3.35")}
            ],
            created_by=self.admin,
        )

        line = purchase.line_items.first()
        self.assertEqual(line.rate, Decimal("3.35"))

        # Master pricing is completely untouched
        master.refresh_from_db()
        self.assertEqual(master.rate_per_piece, Decimal("3.20"))

    def test_master_box_conversion_still_uses_per_piece_rate(self):
        """10. Master Box purchase uses quantity * units_per_master_box * rate_per_piece."""
        # prod_mb: MRP 10.00, 24 units/master box
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("10.00"),
            rate_per_piece=Decimal("6.40"),
        )

        # 2 Master Boxes of prod_mb = 48 pieces
        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[
                {
                    "product": self.prod_mb,
                    "quantity": Decimal("2"),
                    "purchase_unit_name": "master box",
                    "conversion_factor": Decimal("24"),
                    "rate": None,  # should auto-resolve to 6.40/piece
                }
            ],
            created_by=self.admin,
        )

        line = purchase.line_items.first()
        self.assertEqual(line.purchase_unit_name, "master box")
        self.assertEqual(line.quantity, Decimal("2"))
        self.assertEqual(line.conversion_factor, 24)
        self.assertEqual(line.rate, Decimal("6.40"))  # per-piece rate

        # Base pieces = 2 * 24 = 48 pieces
        # Gross = 48 * 6.40 = 307.20
        self.assertEqual(line.taxable_value, Decimal("307.20"))

    def test_changing_supplier_mrp_pricing_later_does_not_modify_historical_purchases(self):
        """11. Historical safety: Changing master pricing later does NOT modify old purchase invoices."""
        master = SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )

        purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[{"product": self.prod_a5, "quantity": Decimal("100"), "rate": None}],
            created_by=self.admin,
        )
        post_purchase(purchase_id=purchase.pk, posted_by=self.admin)
        purchase.refresh_from_db()
        line = purchase.line_items.first()

        orig_total = purchase.total_amount
        orig_rate = line.rate
        orig_unit_cost = line.unit_cost_snapshot

        self.assertEqual(orig_rate, Decimal("3.20"))
        self.assertEqual(orig_unit_cost, Decimal("3.20"))

        # Now change master rate for MRP ₹5.00 to ₹3.40
        self.client.force_authenticate(user=self.admin)
        update_res = self.client.put(
            f"/api/suppliers/{self.supp_a.id}/pricing/{master.id}/",
            {"rate_per_piece": "3.40"},
            format="json",
        )
        self.assertEqual(update_res.status_code, status.HTTP_200_OK)

        # Historical posted purchase is strictly unmodified
        purchase.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(purchase.total_amount, orig_total)
        self.assertEqual(line.rate, orig_rate)
        self.assertEqual(line.unit_cost_snapshot, orig_unit_cost)

        # A NEW purchase receives the updated rate 3.40
        new_purchase = create_purchase(
            supplier=self.supp_a,
            warehouse=self.warehouse,
            invoice_date=timezone.now().date(),
            line_items=[{"product": self.prod_a5, "quantity": Decimal("10"), "rate": None}],
            created_by=self.admin,
        )
        self.assertEqual(new_purchase.line_items.first().rate, Decimal("3.40"))

    def test_admin_and_staff_permissions(self):
        """12. Admin/staff permissions: Staff can view, but cannot modify supplier pricing."""
        # Admin creates pricing
        self.client.force_authenticate(user=self.admin)
        create_res = self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "5.00", "rate_per_piece": "3.20"},
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        pricing_id = create_res.data["id"]

        # Staff can list
        self.client.force_authenticate(user=self.staff)
        staff_get = self.client.get(f"/api/suppliers/{self.supp_a.id}/pricing/")
        self.assertEqual(staff_get.status_code, status.HTTP_200_OK)
        self.assertEqual(len(staff_get.data["pricing"]), 1)

        # Staff cannot create
        staff_post = self.client.post(
            f"/api/suppliers/{self.supp_a.id}/pricing/",
            {"mrp": "10.00", "rate_per_piece": "6.40"},
            format="json",
        )
        self.assertEqual(staff_post.status_code, status.HTTP_403_FORBIDDEN)

        # Staff cannot update
        staff_put = self.client.put(
            f"/api/suppliers/{self.supp_a.id}/pricing/{pricing_id}/",
            {"rate_per_piece": "3.50"},
            format="json",
        )
        self.assertEqual(staff_put.status_code, status.HTTP_403_FORBIDDEN)

        # Staff cannot delete
        staff_del = self.client.delete(f"/api/suppliers/{self.supp_a.id}/pricing/{pricing_id}/")
        self.assertEqual(staff_del.status_code, status.HTTP_403_FORBIDDEN)

    def test_lookup_endpoint_by_mrp(self):
        """Lookup endpoint resolves rate for supplier + product MRP."""
        SupplierPurchasePricing.objects.create(
            supplier=self.supp_a,
            mrp=Decimal("5.00"),
            rate_per_piece=Decimal("3.20"),
        )
        self.client.force_authenticate(user=self.staff)

        # Existing MRP
        res_found = self.client.get(f"/api/suppliers/{self.supp_a.id}/pricing/lookup/?mrp=5.00")
        self.assertEqual(res_found.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(res_found.data["rate_per_piece"]), Decimal("3.20"))

        # Non-existing MRP
        res_none = self.client.get(f"/api/suppliers/{self.supp_a.id}/pricing/lookup/?mrp=99.00")
        self.assertEqual(res_none.status_code, status.HTTP_200_OK)
        self.assertIsNone(res_none.data["rate_per_piece"])
