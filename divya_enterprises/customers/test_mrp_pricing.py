from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from billing.services import create_invoice
from customers.models import Customer, CustomerMRPPricing
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    TaxRate,
)
from inventory.services import ensure_inventory_balance, get_default_warehouse

User = get_user_model()


class CustomerMRPPricingTests(APITestCase):
    """Comprehensive test suite for Feature 3: Customer-wise MRP Pricing."""

    def setUp(self):
        super().setUp()
        self.warehouse = get_default_warehouse()

        self.admin = User.objects.create_user(
            username="pricing_admin", password="password", role=User.ROLE_ADMIN
        )
        self.staff = User.objects.create_user(
            username="pricing_staff", password="password", role=User.ROLE_STAFF
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
        self.category = Category.objects.create(code="SNK_MRP", name="Snacks MRP Test")
        self.mb_attr, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        CategoryAttribute.objects.get_or_create(
            category=self.category, attribute_definition=self.mb_attr
        )

        # Customers
        self.cust_a = Customer.objects.create(
            name="Customer Alpha",
            state="Maharashtra",
            state_code="27",
        )
        self.cust_b = Customer.objects.create(
            name="Customer Beta",
            state="Maharashtra",
            state_code="27",
        )

        # Products: two products with MRP 10.00, one with MRP 5.00
        self.prod_10_a = Product.objects.create(
            name="Chheda Mix 10A",
            brand="Chheda",
            sku="MRP-10A",
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("1000.000"),
        )
        ensure_inventory_balance(product=self.prod_10_a, warehouse=self.warehouse)

        self.prod_10_b = Product.objects.create(
            name="Chheda Poha 10B",
            brand="Chheda",
            sku="MRP-10B",
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("1000.000"),
        )
        ensure_inventory_balance(product=self.prod_10_b, warehouse=self.warehouse)

        self.prod_5 = Product.objects.create(
            name="Chheda Mini 5",
            brand="Chheda",
            sku="MRP-5",
            mrp=Decimal("5.00"),
            tax=self.tax_5,
            current_stock=Decimal("1000.000"),
        )
        ensure_inventory_balance(product=self.prod_5, warehouse=self.warehouse)

        # Master box product with MRP 10.00, 192 units/box
        self.prod_mb = Product.objects.create(
            name="Chheda Box 192",
            brand="Chheda",
            sku="MRP-MB192",
            catalogue_category=self.category,
            mrp=Decimal("10.00"),
            tax=self.tax_5,
            current_stock=Decimal("2000.000"),
        )
        ProductAttributeValue.objects.create(
            product=self.prod_mb, attribute_definition=self.mb_attr, value_integer=192
        )
        ensure_inventory_balance(product=self.prod_mb, warehouse=self.warehouse)

    def test_create_and_retrieve_customer_mrp_pricing(self):
        """Admin can configure MRP pricing for a customer."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            f"/api/customers/{self.cust_a.id}/mrp-pricing/",
            {"mrp": "10.00", "rate_per_piece": "7.00"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(res.data["rate_per_piece"]), Decimal("7.00"))

        # Fetch pricing list
        list_res = self.client.get(f"/api/customers/{self.cust_a.id}/mrp-pricing/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        # Should contain MRP slabs with configured rate for 10.00 and None for 5.00
        configured_10 = next(
            (p for p in list_res.data["pricing"] if Decimal(str(p["mrp"])) == Decimal("10.00")),
            None,
        )
        self.assertIsNotNone(configured_10)
        self.assertEqual(Decimal(str(configured_10["rate_per_piece"])), Decimal("7.00"))

    def test_unique_customer_mrp_updates_existing(self):
        """Posting existing MRP for same customer updates the rate rather than duplicating."""
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f"/api/customers/{self.cust_a.id}/mrp-pricing/",
            {"mrp": "10.00", "rate_per_piece": "7.00"},
            format="json",
        )
        res = self.client.post(
            f"/api/customers/{self.cust_a.id}/mrp-pricing/",
            {"mrp": "10.00", "rate_per_piece": "7.25"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(res.data["rate_per_piece"]), Decimal("7.25"))
        self.assertEqual(
            CustomerMRPPricing.objects.filter(customer=self.cust_a, mrp=Decimal("10.00")).count(),
            1,
        )

    def test_different_customers_different_pricing(self):
        """Different customers have distinct pricing for the same MRP slab."""
        CustomerMRPPricing.objects.create(
            customer=self.cust_a, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.00")
        )
        CustomerMRPPricing.objects.create(
            customer=self.cust_b, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.50")
        )

        self.client.force_authenticate(user=self.staff)
        res_a = self.client.get(f"/api/customers/{self.cust_a.id}/mrp-pricing/lookup/?mrp=10.00")
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(res_a.data["rate_per_piece"])), Decimal("7.00"))

        res_b = self.client.get(f"/api/customers/{self.cust_b.id}/mrp-pricing/lookup/?mrp=10.00")
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(res_b.data["rate_per_piece"])), Decimal("7.50"))

    def test_same_mrp_applies_to_multiple_products(self):
        """Both prod_10_a and prod_10_b share the customer's 10.00 MRP price."""
        CustomerMRPPricing.objects.create(
            customer=self.cust_a, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.00")
        )
        self.client.force_authenticate(user=self.admin)

        # Invoice with both products, omitting rate_charged
        invoice_data = {
            "invoice_number": "INV-MRP-001",
            "customer": self.cust_a.id,
            "payment_type": "credit",
            "invoice_date": str(timezone.localdate()),
            "line_items": [
                {"product": self.prod_10_a.id, "sales_unit_name": "piece", "quantity": 10},
                {"product": self.prod_10_b.id, "sales_unit_name": "piece", "quantity": 20},
            ],
        }
        res = self.client.post("/api/invoices/", invoice_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        lines = res.data["line_items"]
        for line in lines:
            self.assertEqual(Decimal(line["rate_charged"]), Decimal("7.00"))

    def test_unconfigured_mrp_requires_rate(self):
        """If no customer MRP price is configured and no rate is given, validation fails."""
        self.client.force_authenticate(user=self.admin)
        invoice_data = {
            "invoice_number": "INV-MRP-002",
            "customer": self.cust_a.id,
            "payment_type": "credit",
            "invoice_date": str(timezone.localdate()),
            "line_items": [
                {"product": self.prod_5.id, "sales_unit_name": "piece", "quantity": 10},
            ],
        }
        res = self.client.post("/api/invoices/", invoice_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no MRP ₹5.00 pricing configured for customer", str(res.data))

    def test_manual_override_respected(self):
        """Explicit rate_charged overrides configured customer MRP rate."""
        CustomerMRPPricing.objects.create(
            customer=self.cust_a, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.00")
        )
        self.client.force_authenticate(user=self.admin)

        invoice_data = {
            "invoice_number": "INV-MRP-003",
            "customer": self.cust_a.id,
            "payment_type": "credit",
            "invoice_date": str(timezone.localdate()),
            "line_items": [
                {
                    "product": self.prod_10_a.id,
                    "sales_unit_name": "piece",
                    "quantity": 10,
                    "rate_charged": "7.50",
                },
            ],
        }
        res = self.client.post("/api/invoices/", invoice_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        line = res.data["line_items"][0]
        self.assertEqual(Decimal(line["rate_charged"]), Decimal("7.50"))

    def test_master_box_per_piece_calculation(self):
        """Customer MRP rate is per piece. Master box taxable calculation uses base pieces."""
        CustomerMRPPricing.objects.create(
            customer=self.cust_a, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.00")
        )
        self.client.force_authenticate(user=self.admin)

        # 4 boxes * 192 = 768 pieces @ 7.00 = 5376.00 taxable
        invoice_data = {
            "invoice_number": "INV-MRP-004",
            "customer": self.cust_a.id,
            "payment_type": "credit",
            "invoice_date": str(timezone.localdate()),
            "line_items": [
                {
                    "product": self.prod_mb.id,
                    "sales_unit_name": "master box",
                    "quantity": 4,
                    "conversion_factor": 192,
                },
            ],
        }
        res = self.client.post("/api/invoices/", invoice_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        line = res.data["line_items"][0]
        self.assertEqual(Decimal(line["rate_charged"]), Decimal("7.00"))
        self.assertEqual(Decimal(line["taxable_value_snapshot"]), Decimal("5376.00"))

    def test_historical_invoice_not_affected_by_price_change(self):
        """Updating a customer's MRP rate does not change existing posted invoice snapshots."""
        CustomerMRPPricing.objects.create(
            customer=self.cust_a, mrp=Decimal("10.00"), rate_per_piece=Decimal("7.00")
        )
        self.client.force_authenticate(user=self.admin)

        invoice_data = {
            "invoice_number": "INV-MRP-005",
            "customer": self.cust_a.id,
            "payment_type": "credit",
            "invoice_date": str(timezone.localdate()),
            "line_items": [
                {"product": self.prod_10_a.id, "sales_unit_name": "piece", "quantity": 10},
            ],
        }
        res = self.client.post("/api/invoices/", invoice_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        inv_id = res.data["id"]
        original_total = Decimal(res.data["total_amount"])

        # Change customer rate from 7.00 to 8.50
        self.client.post(
            f"/api/customers/{self.cust_a.id}/mrp-pricing/",
            {"mrp": "10.00", "rate_per_piece": "8.50"},
            format="json",
        )

        # Fetch original invoice again
        inv_res = self.client.get(f"/api/invoices/{inv_id}/")
        self.assertEqual(Decimal(inv_res.data["total_amount"]), original_total)
        self.assertEqual(Decimal(inv_res.data["line_items"][0]["rate_charged"]), Decimal("7.00"))

    def test_staff_cannot_create_or_modify_pricing(self):
        """Staff users are forbidden from creating or modifying customer MRP pricing."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(
            f"/api/customers/{self.cust_a.id}/mrp-pricing/",
            {"mrp": "10.00", "rate_per_piece": "7.00"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
