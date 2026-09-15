"""Invoice sales-unit conversion test suite.

Mirrors the purchase unit-conversion tests and adds cases for the new
invoice workflow.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem
from customers.models import Customer
from inventory.models import (
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    ProductAttributeValue,
    PurchaseInvoice,
    StockLedger,
    Supplier,
    TaxRate,
    Warehouse,
)
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse


User = get_user_model()


def make_invoice_test_context(cls):
    """Shared fixture: users, GST business profile, supplier, product with M.Box."""
    cls.admin = User.objects.create_user(
        username="invoice-admin", password="StrongPass123!", role="admin"
    )
    cls.staff = User.objects.create_user(
        username="invoice-staff", password="StrongPass123!", role="staff"
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
    cls.warehouse = get_default_warehouse()
    cls.supplier = Supplier.objects.create(
        name="Test Supplier",
        gstin="27AAACC1234A1Z5",
        state="Maharashtra",
        state_code="27",
    )
    cls.customer = Customer.objects.create(
        name="Test Customer",
        contact_info="9999999999",
        customer_type=Customer.CUSTOMER_TYPE_B2C,
        state_code="27",
    )
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
    # Product WITH master box attribute
    cls.product = Product.objects.create(
        name="Test Chips",
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        mrp=Decimal("10.00"),
        tax=cls.tax_18,
        current_stock=0,
        catalogue_category=cls.category,
    )
    ProductAttributeValue.objects.create(
        product=cls.product,
        attribute_definition=cls.master_box_attr,
        value_integer=192,
    )
    # Product WITHOUT master box attribute
    cls.product_no_box = Product.objects.create(
        name="Test Single",
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        mrp=Decimal("20.00"),
        tax=cls.tax_18,
        current_stock=0,
    )


class InvoiceUnitConversionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        make_invoice_test_context(cls)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def create_stock_via_purchase(self, qty=100, unit="piece", factor=1, rate="6.50"):
        """Helper: create a posted purchase to put stock on hand."""
        payload = {
            "supplier": self.supplier.pk,
            "warehouse": self.warehouse.pk,
            "supplier_invoice_no": f"TEST-{Decimal(str(rate)).quantize(Decimal('0.01'))}",
            "invoice_date": "2026-09-10",
            "tax_mode": "exclusive",
            "line_items": [{
                "product": self.product.pk,
                "quantity": str(qty),
                "purchase_unit_name": unit,
                "conversion_factor": str(factor),
                "rate": str(rate),
                "discount_amount": "0",
            }],
            "post": True,
        }
        response = self.client_as(self.admin).post("/api/purchase-invoices/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def post_invoice(self, payload):
        return self.client_as(self.admin).post("/api/invoices/", payload, format="json")

    def test_invoice_in_pieces_stores_correct_base_quantity(self):
        """Invoice in pieces stores correct base quantity (1:1)."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-PIECES-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "5",
                "sales_unit_name": "piece",
                "conversion_factor": "1",
                "rate_charged": "10.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data["line_items"][0]
        self.assertEqual(Decimal(line["quantity"]), Decimal("5"))
        self.assertEqual(Decimal(line["base_quantity"]), Decimal("5.000"))
        self.assertEqual(line["sales_unit_name"], "piece")
        self.assertEqual(Decimal(line["conversion_factor"]), Decimal("1.000"))
        # Stock deducted by base quantity
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("495.000"))

    def test_invoice_in_master_boxes_stores_correct_base_quantity(self):
        """Invoice in master boxes converts to correct base quantity."""
        self.create_stock_via_purchase(qty=1000, rate="6.50")
        payload = {
            "invoice_number": "INV-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data["line_items"][0]
        self.assertEqual(Decimal(line["quantity"]), Decimal("2"))
        self.assertEqual(line["sales_unit_name"], "master box")
        self.assertEqual(Decimal(line["conversion_factor"]), Decimal("192.000"))
        self.assertEqual(Decimal(line["base_quantity"]), Decimal("384.000"))
        # Stock deducted by base quantity
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("616.000"))

    def test_one_box_equals_configured_units_per_master_box(self):
        """1 box = configured units_per_master_box."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-ONE-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "1",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data["line_items"][0]
        self.assertEqual(Decimal(line["base_quantity"]), Decimal("192.000"))

    def test_two_boxes_equal_double_units(self):
        """2 boxes = 2 × units_per_master_box."""
        self.create_stock_via_purchase(qty=1000, rate="6.50")
        payload = {
            "invoice_number": "INV-TWO-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data["line_items"][0]
        self.assertEqual(Decimal(line["base_quantity"]), Decimal("384.000"))

    def test_invalid_master_box_product_rejected(self):
        """Product without units_per_master_box attribute rejects master box."""
        payload = {
            "invoice_number": "INV-NOBOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product_no_box.pk,
                "quantity": "1",
                "sales_unit_name": "master box",
                "conversion_factor": "50",
                "rate_charged": "1000.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("master box size", str(response.data["line_items"]).lower())

    def test_wrong_conversion_factor_rejected(self):
        """Master box conversion factor must match catalogue exactly."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-WRONGFACTOR-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "100",  # catalogue says 192
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("must be 192", str(response.data["line_items"]))

    def test_insufficient_stock_rejected(self):
        """Invoice exceeding available stock is rejected."""
        self.create_stock_via_purchase(qty=200, rate="6.50")  # 200 pieces on hand
        payload = {
            "invoice_number": "INV-OVER-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],  # needs 384 pieces, only 200 available
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("insufficient stock", str(response.data["line_items"]).lower())
        # Stock unchanged
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("200.000"))

    def test_stock_deduction_uses_base_quantity(self):
        """Stock deduction uses converted base quantity."""
        self.create_stock_via_purchase(qty=1000, rate="6.50")
        payload = {
            "invoice_number": "INV-STOCK-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "3",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],  # 3 * 192 = 576 pieces
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        # 1000 - 576 = 424
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("424.000"))

    def test_cogs_based_on_wac(self):
        """COGS uses WAC, not product cost_price."""
        self.create_stock_via_purchase(qty=500, rate="6.50")  # WAC = 6.50
        # Now change product.cost_price to something different
        self.product.cost_price = Decimal("99.00")
        self.product.save(update_fields=["cost_price", "updated_at"])
        payload = {
            "invoice_number": "INV-COGS-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        response = self.post_invoice(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data["line_items"][0]
        # COGS = 384 * 6.50 = 2496.00 (WAC, not product.cost_price)
        self.assertEqual(line["cost_price_snapshot"], "6.50")
        self.assertEqual(line["cogs_amount"], "2496.00")

    def test_idempotency_prevents_duplicate_sale_movement(self):
        """Same Idempotency-Key with same payload returns same invoice, no double stock deduction."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "IDEMPOTENT-INV",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        key = "invoice-test-idem-key"
        r1 = self.client_as(self.admin).post(
            "/api/invoices/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(r1.status_code, 201, r1.data)
        self.product.refresh_from_db()
        after_first = self.product.current_stock  # 500 - 384 = 116
        r2 = self.client_as(self.admin).post(
            "/api/invoices/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.product.refresh_from_db()
        # Stock deducted only once
        self.assertEqual(self.product.current_stock, after_first)
        # Only one SALE ledger entry for this invoice
        self.assertEqual(
            StockLedger.objects.filter(
                reference_type="invoice", reference_id=r1.data["id"], movement_type=StockLedger.SALE
            ).count(), 1
        )

    def test_draft_then_post_master_box(self):
        """Draft invoice with master box lines posts correctly."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-DRAFT-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        # Create draft
        draft = self.client_as(self.admin).post(
            "/api/invoices/drafts/", payload, format="json"
        )
        self.assertEqual(draft.status_code, 201, draft.data)
        self.assertEqual(draft.data["state"], "DRAFT")
        self.assertEqual(Decimal(draft.data["line_items"][0]["base_quantity"]), Decimal("384.000"))
        # Post it
        post = self.client_as(self.admin).post(
            f"/api/invoices/{draft.data['id']}/post/", {}, format="json"
        )
        self.assertEqual(post.status_code, 200, post.data)
        self.assertEqual(post.data["state"], "POSTED")
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("116.000"))

    def test_cancellation_restoration_uses_base_quantity(self):
        """Invoice cancellation restores stock using base_quantity with SALE_REVERSAL movement."""
        self.create_stock_via_purchase(qty=500, rate="6.50")  # 500 pcs on hand
        payload = {
            "invoice_number": "INV-CANCEL-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        res = self.post_invoice(payload)
        self.assertEqual(res.status_code, 201)
        invoice_id = res.data["id"]
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("116.000"))

        cancel_res = self.client_as(self.admin).post(
            f"/api/invoices/{invoice_id}/cancel/",
            {"reason": "Customer cancelled box order"},
            format="json",
        )
        self.assertEqual(cancel_res.status_code, 200, cancel_res.data)
        self.assertEqual(cancel_res.data["state"], "CANCELLED")
        self.product.refresh_from_db()
        # Stock restored by 384 pieces back to 500.000
        self.assertEqual(self.product.current_stock, Decimal("500.000"))

        reversal = StockLedger.objects.filter(
            reference_type="invoice_cancellation", reference_id=invoice_id
        ).first()
        self.assertIsNotNone(reversal)
        self.assertEqual(reversal.movement_type, StockLedger.SALE_REVERSAL)
        self.assertEqual(reversal.quantity_delta, Decimal("384.000"))
        self.assertEqual(reversal.unit_cost, Decimal("6.50"))

    def test_credit_note_master_box_return(self):
        """Credit note for 1 master box restores 192 base units and computes correct refund."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-CN-BOX-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        inv_res = self.post_invoice(payload)
        self.assertEqual(inv_res.status_code, 201)
        inv_id = inv_res.data["id"]
        line = inv_res.data["line_items"][0]
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("116.000"))

        # Return 1 master box (192 base units)
        cn_res = self.client_as(self.admin).post(
            "/api/credit-notes/",
            {
                "original_invoice": inv_id,
                "reason": "Return 1 damaged box",
                "line_items": [{
                    "invoice_line_item": line["id"],
                    "product": self.product.pk,
                    "quantity": "1",
                    "sales_unit_name": "master box",
                }],
            },
            format="json",
        )
        self.assertEqual(cn_res.status_code, 201, cn_res.data)
        cn = cn_res.data
        # 1 box at 1248.00 + 18% GST (rounded per tax engine) = 1473.00
        self.assertEqual(Decimal(cn["total_amount"]), Decimal("1473.00"))

        # Check stock restoration uses base quantity: 116 + 192 = 308
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("308.000"))

        # Check StockLedger entry
        ledger = StockLedger.objects.filter(
            reference_type="credit_note", reference_id=cn["id"]
        ).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.movement_type, StockLedger.SALES_RETURN)
        self.assertEqual(ledger.quantity_delta, Decimal("192.000"))
        self.assertEqual(ledger.unit_cost, Decimal("6.50"))

        # Check CreditNoteLineItem stores base quantity (192)
        cn_line = CreditNoteLineItem.objects.filter(credit_note_id=cn["id"]).first()
        self.assertEqual(cn_line.quantity, Decimal("192.000"))
        self.assertEqual(cn_line.rate_charged, Decimal("6.50"))

    def test_credit_note_piece_return_against_master_box(self):
        """Returning discrete pieces against a master box invoice line works correctly."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-CN-PCS-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "1",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1920.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        inv_res = self.post_invoice(payload)
        line = inv_res.data["line_items"][0]

        # Return 10 pieces
        cn_res = self.client_as(self.admin).post(
            "/api/credit-notes/",
            {
                "original_invoice": inv_res.data["id"],
                "reason": "Return 10 loose pieces",
                "line_items": [{
                    "invoice_line_item": line["id"],
                    "product": self.product.pk,
                    "quantity": "10",
                    "sales_unit_name": "piece",
                }],
            },
            format="json",
        )
        # 10 pieces * 10/pc = 100.00 taxable + 18.02 GST (proportional line tax) = 118.02
        self.assertEqual(Decimal(cn_res.data["total_amount"]), Decimal("118.02"))

    def test_credit_note_cannot_exceed_billed_base_quantity(self):
        """Credit note reversal cannot exceed the line's original billed base quantity."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-CN-OVER-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "1",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        inv_res = self.post_invoice(payload)
        line = inv_res.data["line_items"][0]

        # Attempt to return 2 master boxes (384 pcs) when only 1 was sold (192 pcs)
        cn_res = self.client_as(self.admin).post(
            "/api/credit-notes/",
            {
                "original_invoice": inv_res.data["id"],
                "reason": "Too many returned",
                "line_items": [{
                    "invoice_line_item": line["id"],
                    "product": self.product.pk,
                    "quantity": "2",
                    "sales_unit_name": "master box",
                }],
            },
            format="json",
        )
        self.assertEqual(cn_res.status_code, 400, cn_res.data)
        self.assertIn("cannot exceed the quantity originally billed", str(cn_res.data["line_items"]))

    def test_persisted_unit_name_and_conversion_factor(self):
        """Line items persist sales_unit_name, conversion_factor, and base_quantity in the database."""
        self.create_stock_via_purchase(qty=500, rate="6.50")
        payload = {
            "invoice_number": "INV-PERSIST-001",
            "customer": self.customer.pk,
            "payment_type": "credit",
            "line_items": [{
                "product": self.product.pk,
                "quantity": "2",
                "sales_unit_name": "master box",
                "conversion_factor": "192",
                "rate_charged": "1248.00",
                "tax_rate": "18",
            }],
            "place_of_supply": "27",
            "tax_mode": "exclusive",
        }
        inv_res = self.post_invoice(payload)
        self.assertEqual(inv_res.status_code, 201)

        # Query database directly
        db_line = InvoiceLineItem.objects.get(invoice_id=inv_res.data["id"])
        self.assertEqual(db_line.sales_unit_name, "master box")
        self.assertEqual(db_line.conversion_factor, Decimal("192.000"))
        self.assertEqual(db_line.base_quantity, Decimal("384.000"))
        self.assertEqual(db_line.quantity, Decimal("2.000"))


class InvoicePricingFieldsTests(APITestCase):
    """Verify purchase rate, invoice selling rate, and COGS snapshots remain authoritative."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="price-admin", password="StrongPass123!", role="admin"
        )
        cls.tax_18, _ = TaxRate.objects.get_or_create(
            name="GST 18%", defaults={"rate": Decimal("18.00")}
        )
        BusinessProfile.objects.create(
            business_name="Test Biz",
            gstin="29TEST8888",
            registered_address="Addr",
            state="Karnataka",
            state_code="29",
        )
        cls.warehouse = get_default_warehouse()
        cls.supplier = Supplier.objects.create(
            name="Price Supplier", gstin="29AAACC1234A1Z5", state="Karnataka", state_code="29"
        )
        cls.customer = Customer.objects.create(
            name="Price Customer", contact_info="9999999999", customer_type=Customer.CUSTOMER_TYPE_B2C, state_code="29"
        )
        cls.product = Product.objects.create(
            name="Price Test Product",
            base_unit=Product.UNIT_PIECE,
            unit_type=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            mrp=Decimal("100.00"),
            tax=cls.tax_18,
            current_stock=0,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_purchase_rate_remains_on_line(self):
        """Purchase line rate is the actual supplier rate."""
        from inventory.purchase_services import create_purchase
        purchase = create_purchase(
            supplier=self.supplier, warehouse=self.warehouse,
            invoice_date="2026-09-10",
            line_items=[{"product": self.product, "quantity": Decimal("100"), "rate": Decimal("6.50")}],
            created_by=self.admin, post=True,
        )
        line = purchase.line_items.get()
        self.assertEqual(line.rate, Decimal("6.50"))

    def test_invoice_rate_remains_on_line(self):
        """Invoice line rate_charged is the actual selling rate."""
        from inventory.purchase_services import create_purchase
        from billing.services import create_invoice
        create_purchase(
            supplier=self.supplier, warehouse=Warehouse.objects.get(code="MAIN"),
            invoice_date="2026-09-10",
            line_items=[{"product": self.product, "quantity": Decimal("100"), "rate": Decimal("6.50")}],
            created_by=self.admin, post=True,
        )
        invoice = create_invoice(
            customer=self.customer, invoice_number="INV-PRICE-001",
            created_by=self.admin, payment_type="credit",
            line_items=[{"product": self.product, "quantity": "5", "rate_charged": "10.00", "tax_rate": "18"}],
        )
        line = invoice.line_items.get()
        self.assertEqual(line.rate_charged, Decimal("10.00"))

    def test_historical_cogs_snapshot_unchanged_by_product_cost_change(self):
        """COGS snapshot on invoice line remains unchanged if product.cost_price changes later."""
        from inventory.purchase_services import create_purchase
        from billing.services import create_invoice
        # Receive stock
        create_purchase(
            supplier=self.supplier, warehouse=self.warehouse,
            invoice_date="2026-09-10",
            line_items=[{"product": self.product, "quantity": Decimal("100"), "rate": Decimal("6.50")}],
            created_by=self.admin, post=True,
        )
        # Sell some
        invoice = create_invoice(
            customer=self.customer, invoice_number="INV-COGS-SNAP",
            created_by=self.admin, payment_type="credit",
            line_items=[{"product": self.product, "quantity": "10", "rate_charged": "10.00", "tax_rate": "18"}],
        )
        line = invoice.line_items.get()
        original_cogs = line.cogs_amount
        # Change product cost
        self.product.cost_price = Decimal("99.00")
        self.product.save(update_fields=["cost_price", "updated_at"])
        line.refresh_from_db()
        self.assertEqual(line.cogs_amount, original_cogs)
        self.assertEqual(line.cost_price_snapshot, Decimal("6.50"))

    def test_reports_use_historical_values(self):
        """Reports use historical snapshots, not current product prices."""
        from inventory.purchase_services import create_purchase
        from billing.services import create_invoice
        from billing.reports import ProductSalesReportView
        from rest_framework.request import Request
        from django.test import RequestFactory
        create_purchase(
            supplier=self.supplier, warehouse=self.warehouse,
            invoice_date="2026-09-10",
            line_items=[{"product": self.product, "quantity": Decimal("100"), "rate": Decimal("6.50")}],
            created_by=self.admin, post=True,
        )
        create_invoice(
            customer=self.customer, invoice_number="INV-REPORT-001",
            created_by=self.admin, payment_type="credit",
            line_items=[{"product": self.product, "quantity": "5", "rate_charged": "10.00", "tax_rate": "18"}],
        )
        # Change product prices
        self.product.cost_price = Decimal("99.00")
        self.product.default_price = Decimal("999.00")
        self.product.save(update_fields=["cost_price", "default_price", "updated_at"])
        # Call product sales report
        factory = RequestFactory()
        today = timezone.localdate()
        req = factory.get(f"/reports/products/?from={today}&to={today}")
        req.user = self.admin
        view = ProductSalesReportView.as_view()
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        products = resp.data["products"]
        self.assertEqual(len(products), 1)
        # COGS uses WAC 6.50 * 5 = 32.50, NOT product.cost_price
        self.assertEqual(Decimal(str(products[0]["cogs"])), Decimal("32.50"))
        # Rate is the actual invoice rate, not product.default_price (50.00 + 10.00 GST rounded = 60.00)
        self.assertEqual(Decimal(str(products[0]["sales_value"])), Decimal("60.00"))

    def test_flows_work_without_product_prices(self):
        """Purchases, invoices, and reports work when product cost_price/default_price are zero."""
        # Product created with default zero prices
        product = self.product
        product.cost_price = Decimal("0.00")
        product.default_price = Decimal("0.00")
        product.save(update_fields=["cost_price", "default_price", "updated_at"])
        from inventory.purchase_services import create_purchase
        from billing.services import create_invoice
        # Purchase works
        purchase = create_purchase(
            supplier=self.supplier, warehouse=self.warehouse,
            invoice_date="2026-09-10",
            line_items=[{"product": product, "quantity": Decimal("100"), "rate": Decimal("6.50")}],
            created_by=self.admin, post=True,
        )
        self.assertEqual(purchase.line_items.get().rate, Decimal("6.50"))
        # Invoice works with explicit rate
        invoice = create_invoice(
            customer=self.customer, invoice_number="INV-NOPRICE-001",
            created_by=self.admin, payment_type="credit",
            line_items=[{"product": product, "quantity": "5", "rate_charged": "10.00", "tax_rate": "18"}],
        )
        self.assertEqual(invoice.line_items.get().rate_charged, Decimal("10.00"))