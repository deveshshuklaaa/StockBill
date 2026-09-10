"""Purchase → stock receipt → weighted-average cost test suite.

Covers the approved V1 design:
- lifecycle: draft (no inventory effect) → post (atomic receipt) → cancel
  (compensating reversal)
- costing: pre-tax, post-discount per-base-unit cost basis; GST excluded
- unit conversion: pieces always valid; master box only when the product's
  units_per_master_box attribute exists and the factor matches it
- GST: CGST/SGST intra-state, IGST inter-state, inclusive/exclusive modes
- snapshots: posted lines never consult mutable masters
- numbering: PI/FY/000001 per financial year, sequential
- idempotency: same key + same payload → one purchase; different payload → 409
- permissions: admin-only purchase endpoints
- concurrency: two posted purchases blend into the correct weighted average
"""

import datetime
import threading
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from billing.models import AuditLog, BusinessProfile
from customers.models import Customer
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    PurchaseInvoice,
    PurchaseLineItem,
    StockLedger,
    Supplier,
    TaxRate,
)
from inventory.purchase_numbering import financial_year_code
from inventory.purchase_services import (
    cancel_purchase,
    create_purchase,
    post_purchase,
)
from inventory.services import adjust_inventory, get_default_warehouse


User = get_user_model()


def make_context(cls):
    """Shared fixture: users, GST business profile, supplier, products."""
    cls.admin = User.objects.create_user(
        username="purchase-admin", password="StrongPass123!", role="admin"
    )
    cls.staff = User.objects.create_user(
        username="purchase-staff", password="StrongPass123!", role="staff"
    )
    BusinessProfile.objects.create(
        business_name="Divya Enterprises",
        gstin="27DIVYA1234A1Z5",
        registered_address="Shop 1, Main Road, Mumbai",
        state="Maharashtra",
        state_code="27",
    )
    cls.tax_18, _ = TaxRate.objects.get_or_create(
        name="GST 18%", defaults={"rate": Decimal("18.00")}
    )
    cls.tax_18.rate = Decimal("18.00")
    cls.tax_18.save(update_fields=["rate"])
    cls.tax_12, _ = TaxRate.objects.get_or_create(
        name="GST 12%", defaults={"rate": Decimal("12.00")}
    )
    cls.warehouse = get_default_warehouse()
    cls.supplier_intra = Supplier.objects.create(
        name="Chheda Specialities Foods Pvt. Ltd.",
        gstin="27AAACC1234A1Z5",
        state="Maharashtra",
        state_code="27",
    )
    cls.supplier_inter = Supplier.objects.create(
        name="Gujarat Snacks Pvt. Ltd.",
        gstin="24AAAGH5678B1Z3",
        state="Gujarat",
        state_code="24",
    )
    cls.product = Product.objects.create(
        name="Chheda's Yellow Banana Chips",
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        default_price=10,
        cost_price=0,
        mrp=10,
        tax=cls.tax_18,
        current_stock=0,
    )
    cls.product_other = Product.objects.create(
        name="Plain Product",
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        default_price=20,
        cost_price=0,
        tax=cls.tax_18,
        current_stock=0,
    )
    # Catalogue-style master box attribute for cls.product only.
    cls.category = Category.objects.create(code="packaged-food", name="Packaged Food")
    cls.master_box_attr = AttributeDefinition.objects.create(
        code="units_per_master_box",
        name="Units per Master Box",
        data_type=AttributeDefinition.TYPE_INTEGER,
    )
    CategoryAttribute.objects.create(
        category=cls.category,
        attribute_definition=cls.master_box_attr,
        is_required=False,
    )
    cls.product.catalogue_category = cls.category
    cls.product.save(update_fields=["catalogue_category"])
    from inventory.models import ProductAttributeValue

    ProductAttributeValue.objects.create(
        product=cls.product,
        attribute_definition=cls.master_box_attr,
        value_integer=192,
    )


class PurchaseAPITestBase(APITestCase):
    """Shared fixture: users, GST business profile, supplier, products."""

    @classmethod
    def setUpTestData(cls):
        make_context(cls)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def purchase_payload(self, **overrides):
        payload = {
            "supplier": self.supplier_intra.pk,
            "warehouse": self.warehouse.pk,
            "supplier_invoice_no": "CHHEDA-BILL-001",
            "invoice_date": "2026-09-10",
            "tax_mode": "exclusive",
            "line_items": [
                {
                    "product": self.product.pk,
                    "quantity": "100",
                    "purchase_unit_name": "piece",
                    "conversion_factor": "1",
                    "rate": "6.50",
                    "discount_amount": "0",
                }
            ],
        }
        payload.update(overrides)
        return payload


class PurchaseLifecycleTests(PurchaseAPITestBase):
    def test_draft_purchase_does_not_touch_inventory(self):
        balance_before = InventoryBalance.objects.filter(
            product=self.product, warehouse=self.warehouse
        ).first()
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", self.purchase_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        purchase = PurchaseInvoice.objects.get(pk=response.data["id"])
        self.assertEqual(purchase.state, "DRAFT")
        self.assertIsNone(purchase.purchase_number)
        self.assertFalse(
            StockLedger.objects.filter(movement_type=StockLedger.PURCHASE).exists()
        )
        self.assertEqual(
            InventoryBalance.objects.filter(
                product=self.product, warehouse=self.warehouse
            ).count(),
            0 if balance_before is None else 1,
        )
        self.assertEqual(
            InventoryBalance.objects.filter(
                product=self.product, warehouse=self.warehouse
            ).first().quantity_on_hand
            if balance_before is not None
            else Decimal("0"),
            balance_before.quantity_on_hand if balance_before else Decimal("0"),
        )

    def test_create_with_post_receives_stock_and_ledger(self):
        payload = self.purchase_payload()
        payload["post"] = True
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["state"], "POSTED")
        self.assertRegex(response.data["purchase_number"], r"^PI/\d{2}-\d{2}/000001$")

        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("100.000"))
        self.assertEqual(balance.average_cost, Decimal("6.50"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("100.000"))

        movement = StockLedger.objects.get(
            movement_type=StockLedger.PURCHASE,
            reference_type="purchase_invoice",
            reference_id=response.data["id"],
        )
        self.assertEqual(movement.quantity_change, Decimal("100.000"))
        self.assertEqual(movement.unit_cost, Decimal("6.50"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="purchase_posted", entity_id=response.data["id"]
            ).exists()
        )

    def test_post_draft_endpoint_receives_stock(self):
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", self.purchase_payload(), format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        response = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{created.data['id']}/post/", format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "POSTED")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("100.000"))

        # Posting twice is idempotent.
        again = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{created.data['id']}/post/", format="json"
        )
        self.assertEqual(again.status_code, 200, again.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity_on_hand, Decimal("100.000"))
        self.assertEqual(
            StockLedger.objects.filter(movement_type=StockLedger.PURCHASE).count(), 1
        )

    def test_draft_edit_and_delete(self):
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", self.purchase_payload(), format="json"
        )
        purchase_id = created.data["id"]
        updated = self.client_as(self.admin).patch(
            f"/api/purchase-invoices/{purchase_id}/",
            {
                "supplier_invoice_no": "CHHEDA-BILL-001-REV",
                "line_items": [
                    {
                        "product": self.product.pk,
                        "quantity": "50",
                        "rate": "7.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        purchase = PurchaseInvoice.objects.get(pk=purchase_id)
        self.assertEqual(purchase.supplier_invoice_no, "CHHEDA-BILL-001-REV")
        line = purchase.line_items.get()
        self.assertEqual(line.quantity, Decimal("50"))
        self.assertEqual(line.rate, Decimal("7.00"))
        self.assertEqual(purchase.taxable_total, Decimal("350.00"))
        self.assertEqual(purchase.total_amount, Decimal("413.00"))

        deleted = self.client_as(self.admin).delete(
            f"/api/purchase-invoices/{purchase_id}/"
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(PurchaseInvoice.objects.filter(pk=purchase_id).exists())
        self.assertFalse(
            StockLedger.objects.filter(movement_type=StockLedger.PURCHASE).exists()
        )

    def test_posted_purchase_is_immutable_via_patch(self):
        payload = self.purchase_payload()
        payload["post"] = True
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        purchase_id = created.data["id"]
        patched = self.client_as(self.admin).patch(
            f"/api/purchase-invoices/{purchase_id}/",
            {"supplier_invoice_no": "TAMPERED"},
            format="json",
        )
        self.assertEqual(patched.status_code, 400, patched.data)
        self.assertIn("state", patched.data)

    def test_cancel_posted_purchase_reverses_stock_and_average(self):
        payload = self.purchase_payload()
        payload["post"] = True
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        purchase_id = created.data["id"]

        cancelled = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{purchase_id}/cancel/",
            {"reason": "Wrong entry"},
            format="json",
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["state"], "CANCELLED")

        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("0.000"))
        self.assertEqual(balance.average_cost, Decimal("0.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("0.000"))
        reversal = StockLedger.objects.get(
            movement_type=StockLedger.PURCHASE_REVERSAL,
            reference_type="purchase_invoice_cancellation",
            reference_id=purchase_id,
        )
        self.assertEqual(reversal.quantity_change, Decimal("-100.000"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="purchase_cancelled", entity_id=purchase_id
            ).exists()
        )

        # Double cancel is rejected.
        again = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{purchase_id}/cancel/",
            {"reason": "Again"},
            format="json",
        )
        self.assertEqual(again.status_code, 400, again.data)

    def test_cancel_blocked_when_stock_already_sold(self):
        payload = self.purchase_payload()
        payload["post"] = True
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        purchase_id = created.data["id"]
        adjust_inventory(
            product=self.product,
            quantity_delta=Decimal("-60"),
            movement_type=StockLedger.SALE,
            created_by=self.admin,
            unit_cost=Decimal("6.50"),
        )
        blocked = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{purchase_id}/cancel/",
            {"reason": "Try to cancel"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400, blocked.data)
        purchase = PurchaseInvoice.objects.get(pk=purchase_id)
        self.assertEqual(purchase.state, "POSTED")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("40.000"))

    def test_cancel_draft_not_allowed_via_cancel_endpoint(self):
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", self.purchase_payload(), format="json"
        )
        response = self.client_as(self.admin).post(
            f"/api/purchase-invoices/{created.data['id']}/cancel/",
            {"reason": "Nope"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)


class PurchaseCostingTests(PurchaseAPITestBase):
    def post_direct(self, quantity, rate, **extra):
        purchase = create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=datetime.date(2026, 9, 10),
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal(quantity),
                    "rate": Decimal(rate),
                    **extra,
                }
            ],
            created_by=self.admin,
            post=True,
        )
        return purchase

    def test_first_purchase_sets_average(self):
        self.post_direct("100", "6.00")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("100.000"))
        self.assertEqual(balance.average_cost, Decimal("6.00"))

    def test_second_purchase_blends_weighted_average(self):
        self.post_direct("100", "6.00")
        self.post_direct("50", "7.00")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("150.000"))
        self.assertEqual(balance.average_cost, Decimal("6.33"))

    def test_discount_lowers_cost_basis(self):
        # 100 pieces @ ₹6.50 with ₹50 line discount → taxable 600 → cost 6.00
        purchase = create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=datetime.date(2026, 9, 10),
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal("100"),
                    "rate": Decimal("6.50"),
                    "discount_amount": Decimal("50"),
                }
            ],
            created_by=self.admin,
            post=True,
        )
        line = purchase.line_items.get()
        self.assertEqual(line.taxable_value, Decimal("600.00"))
        self.assertEqual(line.unit_cost_snapshot, Decimal("6.00"))
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.average_cost, Decimal("6.00"))

    def test_gst_excluded_from_cost(self):
        self.post_direct("100", "6.00")
        line = PurchaseLineItem.objects.filter(product=self.product).latest("id")
        self.assertEqual(line.cgst_amount, Decimal("54.00"))
        self.assertEqual(line.sgst_amount, Decimal("54.00"))
        self.assertEqual(line.line_total, Decimal("708.00"))
        # Cost basis stays pre-tax.
        self.assertEqual(line.unit_cost_snapshot, Decimal("6.00"))
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.average_cost, Decimal("6.00"))

    def test_inclusive_mode_tax_extraction(self):
        purchase = create_purchase(
            supplier=self.supplier_intra,
            warehouse=self.warehouse,
            invoice_date=datetime.date(2026, 9, 10),
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal("100"),
                    "rate": Decimal("7.08"),  # 6.00 + 18% tax inclusive
                }
            ],
            created_by=self.admin,
            post=True,
            tax_mode=PurchaseInvoice.TAX_MODE_INCLUSIVE,
        )
        line = purchase.line_items.get()
        self.assertEqual(line.taxable_value, Decimal("600.00"))
        self.assertEqual(line.unit_cost_snapshot, Decimal("6.00"))

    def test_historical_cost_survives_product_cost_price_change(self):
        self.post_direct("100", "6.00")
        self.product.cost_price = Decimal("99.00")
        self.product._allow_stock_cache_update = True
        self.product.save(update_fields=["cost_price", "updated_at"])
        line = PurchaseLineItem.objects.filter(product=self.product).latest("id")
        self.assertEqual(line.unit_cost_snapshot, Decimal("6.00"))
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.average_cost, Decimal("6.00"))

    def test_cancel_restores_previous_average(self):
        self.post_direct("100", "6.00")
        second = self.post_direct("50", "7.00")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.average_cost, Decimal("6.33"))
        cancel_purchase(
            purchase_id=second.pk, cancelled_by=self.admin, reason="Rollback"
        )
        balance.refresh_from_db()
        self.assertEqual(balance.quantity_on_hand, Decimal("100.000"))
        self.assertEqual(balance.average_cost, Decimal("6.00"))


class PurchaseUnitConversionTests(PurchaseAPITestBase):
    def test_master_box_conversion(self):
        payload = self.purchase_payload()
        payload["post"] = True
        payload["line_items"] = [
            {
                "product": self.product.pk,
                "quantity": "5",
                "purchase_unit_name": "master box",
                "conversion_factor": "192",
                "rate": "1248.00",
            }
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        line = PurchaseLineItem.objects.get(purchase_invoice=response.data["id"])
        self.assertEqual(line.base_quantity, Decimal("960.000"))
        self.assertEqual(line.conversion_factor, Decimal("192"))
        self.assertEqual(line.unit_cost_snapshot, Decimal("6.50"))
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("960.000"))

    def test_master_box_rejected_without_catalogue_attribute(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {
                "product": self.product_other.pk,  # no M.Box attribute
                "quantity": "2",
                "purchase_unit_name": "master box",
                "conversion_factor": "50",
                "rate": "500",
            }
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("master box size", str(response.data["line_items"]))

    def test_master_box_factor_must_match_catalogue(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {
                "product": self.product.pk,
                "quantity": "2",
                "purchase_unit_name": "master box",
                "conversion_factor": "100",  # catalogue says 192
                "rate": "650",
            }
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("must be 192", str(response.data["line_items"]))

    def test_unknown_purchase_unit_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {
                "product": self.product.pk,
                "quantity": "2",
                "purchase_unit_name": "carton",
                "conversion_factor": "10",
                "rate": "60",
            }
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_duplicate_product_lines_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {
                "product": self.product.pk,
                "quantity": "10",
                "rate": "6.00",
            },
            {
                "product": self.product.pk,
                "quantity": "20",
                "rate": "6.00",
            },
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)


class PurchaseGSTTests(PurchaseAPITestBase):
    def test_intra_state_purchase_splits_cgst_sgst(self):
        payload = self.purchase_payload()
        payload["post"] = True
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        purchase = PurchaseInvoice.objects.get(pk=response.data["id"])
        self.assertEqual(purchase.taxable_total, Decimal("650.00"))
        self.assertEqual(purchase.cgst_total, Decimal("58.50"))
        self.assertEqual(purchase.sgst_total, Decimal("58.50"))
        self.assertEqual(purchase.igst_total, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("767.00"))
        self.assertEqual(
            purchase.supplier_gstin_snapshot, "27AAACC1234A1Z5"
        )
        self.assertEqual(purchase.supplier_state_code_snapshot, "27")

    def test_inter_state_purchase_uses_igst(self):
        payload = self.purchase_payload()
        payload["supplier"] = self.supplier_inter.pk
        payload["post"] = True
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        purchase = PurchaseInvoice.objects.get(pk=response.data["id"])
        self.assertEqual(purchase.igst_total, Decimal("117.00"))
        self.assertEqual(purchase.cgst_total, Decimal("0.00"))
        self.assertEqual(purchase.sgst_total, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("767.00"))

    def test_mismatched_tax_rate_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {
                "product": self.product.pk,
                "quantity": "10",
                "rate": "6.00",
                "tax_rate": "12",  # product's configured rate is 18
            }
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_supplier_gstin_snapshot_immutable(self):
        payload = self.purchase_payload()
        payload["post"] = True
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        purchase = PurchaseInvoice.objects.get(pk=response.data["id"])
        self.supplier_intra.gstin = "27ZZZZZ9999C1Z9"
        self.supplier_intra.save(update_fields=["gstin"])
        purchase.refresh_from_db()
        self.assertEqual(purchase.supplier_gstin_snapshot, "27AAACC1234A1Z5")


class PurchaseNumberingTests(PurchaseAPITestBase):
    def test_numbers_are_sequential_per_financial_year(self):
        numbers = []
        for _ in range(3):
            purchase = create_purchase(
                supplier=self.supplier_intra,
                warehouse=self.warehouse,
                invoice_date=datetime.date(2026, 9, 10),
                line_items=[
                    {
                        "product": self.product,
                        "quantity": Decimal("1"),
                        "rate": Decimal("1.00"),
                    }
                ],
                created_by=self.admin,
                post=True,
            )
            numbers.append(purchase.purchase_number)
        self.assertEqual(
            numbers,
            [
                "PI/26-27/000001",
                "PI/26-27/000002",
                "PI/26-27/000003",
            ],
        )

    def test_financial_year_boundary(self):
        self.assertEqual(financial_year_code(datetime.date(2026, 3, 31)), "25-26")
        self.assertEqual(financial_year_code(datetime.date(2026, 4, 1)), "26-27")
        self.assertEqual(financial_year_code(datetime.date(2026, 9, 10)), "26-27")

    def test_next_number_preview_does_not_consume(self):
        client = self.client_as(self.admin)
        first = client.get("/api/purchase-invoices/next-number/?date=2026-09-10")
        self.assertEqual(first.status_code, 200, first.data)
        again = client.get("/api/purchase-invoices/next-number/?date=2026-09-10")
        self.assertEqual(again.data["next_number"], first.data["next_number"])
        payload = self.purchase_payload()
        payload["post"] = True
        created = client.post("/api/purchase-invoices/", payload, format="json")
        self.assertEqual(created.data["purchase_number"], first.data["next_number"])


class PurchaseIdempotencyTests(PurchaseAPITestBase):
    def test_same_key_same_payload_returns_original(self):
        payload = self.purchase_payload()
        payload["post"] = True
        key = str(uuid.uuid4())
        first = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(PurchaseInvoice.objects.count(), 1)
        self.assertEqual(
            StockLedger.objects.filter(movement_type=StockLedger.PURCHASE).count(), 1
        )

    def test_same_key_different_payload_conflicts(self):
        payload = self.purchase_payload()
        payload["post"] = True
        key = str(uuid.uuid4())
        first = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(first.status_code, 201, first.data)
        payload["line_items"][0]["rate"] = "9.99"
        second = self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(second.status_code, 409, second.data)


class PurchasePermissionTests(PurchaseAPITestBase):
    def test_staff_cannot_list_create_or_mutate_purchases(self):
        client = self.client_as(self.staff)
        self.assertEqual(client.get("/api/purchase-invoices/").status_code, 403)
        self.assertEqual(
            client.post("/api/purchase-invoices/", self.purchase_payload(), format="json").status_code,
            403,
        )
        payload = self.purchase_payload()
        payload["post"] = True
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        purchase_id = created.data["id"]
        self.assertEqual(
            client.post(f"/api/purchase-invoices/{purchase_id}/post/").status_code, 403
        )
        self.assertEqual(
            client.post(
                f"/api/purchase-invoices/{purchase_id}/cancel/", {"reason": "x"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            client.get(f"/api/purchase-invoices/{purchase_id}/").status_code, 403
        )
        self.assertEqual(
            client.get("/api/purchase-invoices/next-number/").status_code, 403
        )

    def test_unauthenticated_requests_rejected(self):
        anonymous = APIClient()
        self.assertIn(
            anonymous.get("/api/purchase-invoices/").status_code, {401, 403}
        )

    def test_staff_still_sees_supplier_names(self):
        response = self.client_as(self.staff).get("/api/suppliers/")
        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertNotIn("outstanding", str(row.keys()))


class PurchaseValidationTests(PurchaseAPITestBase):
    def test_supplier_bill_no_unique_per_supplier(self):
        payload = self.purchase_payload()
        first = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        duplicate = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertTrue(
            "unique" in str(duplicate.data).lower(),
            duplicate.data,
        )

    def test_same_bill_no_allowed_for_different_supplier(self):
        payload = self.purchase_payload()
        first = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        payload["supplier"] = self.supplier_inter.pk
        second = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(second.status_code, 201, second.data)

    def test_empty_lines_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = []
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_zero_quantity_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {"product": self.product.pk, "quantity": "0", "rate": "6.00"}
        ]
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_inactive_supplier_rejected(self):
        self.supplier_intra.is_active = False
        self.supplier_intra.save(update_fields=["is_active"])
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", self.purchase_payload(), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("supplier", response.data)

    def test_inactive_product_rejected(self):
        payload = self.purchase_payload()
        payload["line_items"] = [
            {"product": self.product_other.pk, "quantity": "1", "rate": "5"}
        ]
        self.product_other.is_active = False
        self.product_other.save(update_fields=["is_active"])
        response = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)


class WarehouseIsolationTests(PurchaseAPITestBase):
    def test_purchase_isolated_to_target_warehouse(self):
        from inventory.models import Warehouse

        other = Warehouse.objects.create(
            name="Second Warehouse", code="SECOND"
        )
        payload = self.purchase_payload()
        payload["post"] = True
        payload["warehouse"] = self.warehouse.pk
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        main_balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(main_balance.quantity_on_hand, Decimal("100.000"))
        self.assertFalse(
            InventoryBalance.objects.filter(
                product=self.product, warehouse=other
            ).exists()
        )
        movements = StockLedger.objects.filter(
            movement_type=StockLedger.PURCHASE
        )
        self.assertTrue(all(m.warehouse_id == self.warehouse.pk for m in movements))


class ConcurrentPurchaseTests(TransactionTestCase):
    """Two purchases posted concurrently must blend, not lose updates."""

    def setUp(self):
        make_context(self)

    def test_concurrent_posts_blend_weighted_average(self):
        results = []

        def worker(quantity, rate):
            try:
                purchase = create_purchase(
                    supplier=self.supplier_intra,
                    warehouse=self.warehouse,
                    invoice_date=datetime.date(2026, 9, 10),
                    line_items=[
                        {
                            "product": self.product,
                            "quantity": Decimal(quantity),
                            "rate": Decimal(rate),
                        }
                    ],
                    created_by=self.admin,
                    post=True,
                )
                results.append(purchase.purchase_number)
            except Exception as error:  # pragma: no cover - surfaced in assert
                results.append(f"ERROR: {error}")

        first = threading.Thread(target=worker, args=("100", "6.00"))
        second = threading.Thread(target=worker, args=("50", "7.00"))
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(len(results), 2, results)
        self.assertNotIn(results[0], [None, ""])
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("150.000"))
        # (100×6 + 50×7) / 150 = 6.333… → 6.33
        self.assertEqual(balance.average_cost, Decimal("6.33"))
        self.assertEqual(len(set(results)), 2, "concurrent posts must get distinct numbers")


class SupplierAPITests(PurchaseAPITestBase):
    def test_supplier_crud_with_gstin_validation(self):
        payload = {
            "name": "New Supplier",
            "gstin": "27INVALID",
            "state_code": "27",
        }
        response = self.client_as(self.admin).post(
            "/api/suppliers/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("gstin", response.data)

        payload["gstin"] = "27AAACC1234A1Z5"
        response = self.client_as(self.admin).post(
            "/api/suppliers/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        supplier_id = response.data["id"]

        updated = self.client_as(self.admin).patch(
            f"/api/suppliers/{supplier_id}/",
            {"contact_info": "9876543210"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)

        deleted = self.client_as(self.admin).delete(f"/api/suppliers/{supplier_id}/")
        self.assertEqual(deleted.status_code, 204)
        supplier = Supplier.objects.get(pk=supplier_id)
        self.assertFalse(supplier.is_active)

    def test_supplier_with_purchases_cannot_be_hard_deleted(self):
        payload = self.purchase_payload()
        payload["post"] = True
        created = self.client_as(self.admin).post(
            "/api/purchase-invoices/", payload, format="json"
        )
        self.assertEqual(created.status_code, 201)
        response = self.client_as(self.admin).delete(
            f"/api/suppliers/{self.supplier_intra.pk}/"
        )
        self.assertEqual(response.status_code, 204)
        self.supplier_intra.refresh_from_db()
        self.assertFalse(self.supplier_intra.is_active)
        self.assertTrue(Supplier.objects.filter(pk=self.supplier_intra.pk).exists())

    def test_supplier_search_and_status_filters(self):
        Supplier.objects.create(name="Unique Supplier Name", is_active=False)
        client = self.client_as(self.admin)
        search = client.get("/api/suppliers/?search=Unique")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.data["count"], 1)
        inactive = client.get("/api/suppliers/?is_active=false")
        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(inactive.data["count"], 1)


class PurchaseListFilterTests(PurchaseAPITestBase):
    def test_list_filters_by_state_supplier_and_search(self):
        client = self.client_as(self.admin)
        draft_payload = self.purchase_payload()
        client.post("/api/purchase-invoices/", draft_payload, format="json")
        posted_payload = self.purchase_payload()
        posted_payload["post"] = True
        posted_payload["supplier_invoice_no"] = "CHHEDA-BILL-002"
        client.post("/api/purchase-invoices/", posted_payload, format="json")

        drafts = client.get("/api/purchase-invoices/?state=DRAFT")
        self.assertEqual(drafts.data["count"], 1)
        posted = client.get("/api/purchase-invoices/?state=POSTED")
        self.assertEqual(posted.data["count"], 1)
        by_supplier = client.get(
            f"/api/purchase-invoices/?supplier={self.supplier_intra.pk}"
        )
        self.assertEqual(by_supplier.data["count"], 2)
        by_search = client.get("/api/purchase-invoices/?search=CHHEDA-BILL-002")
        self.assertEqual(by_search.data["count"], 1)
        invalid = client.get("/api/purchase-invoices/?state=BOGUS")
        self.assertEqual(invalid.status_code, 400)


class SalesRegressionTests(PurchaseAPITestBase):
    """Purchases must not disturb the verified sales pipeline."""

    def test_sales_flow_with_purchased_stock(self):
        # Receive stock via purchase, then sell it.
        self.client_as(self.admin).post(
            "/api/purchase-invoices/",
            {**self.purchase_payload(), "post": True},
            format="json",
        )
        customer = Customer.objects.create(name="Retail Customer", state_code="27")
        invoice_payload = {
            "invoice_number": "SALES-REG-1001",
            "customer": customer.pk,
            "payment_type": "credit",
            "line_items": [
                {
                    "product": self.product.pk,
                    "quantity": "10",
                    "rate_charged": "10",
                    "tax_rate": "18",
                }
            ],
        }
        invoice = self.client_as(self.admin).post(
            "/api/invoices/", invoice_payload, format="json"
        )
        self.assertEqual(invoice.status_code, 201, invoice.data)
        line = (
            PurchaseLineItem.objects.filter(product=self.product)
            .order_by("-id")
            .first()
        )
        from billing.models import Invoice, InvoiceLineItem

        sale_line = InvoiceLineItem.objects.get(invoice__invoice_number="SALES-REG-1001")
        # COGS must use the purchase-derived weighted average (6.50).
        self.assertEqual(sale_line.cost_price_snapshot, Decimal("6.50"))
        self.assertEqual(sale_line.cogs_amount, Decimal("65.00"))

        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("90.000"))
