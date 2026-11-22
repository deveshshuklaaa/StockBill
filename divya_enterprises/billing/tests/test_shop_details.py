"""Release B3: every shop detail comes from the Business Profile, never code."""

from decimal import Decimal as D
from io import BytesIO

import openpyxl
import pymupdf
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice
from billing.pdf_engine import build_invoice_a5_pdf, layout_header_name
from billing.reports import build_sales_gst_report_xlsx, get_sales_gst_report_data
from billing.services import (
    PROFILE_INCOMPLETE_MESSAGE,
    build_item_summary_xlsx,
    build_selected_invoices_item_summary,
    create_invoice,
    post_invoice,
)
from customers.models import Customer
from inventory.models import Product, Supplier, TaxRate
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse

User = get_user_model()
SHOP = dict(business_name="Sharma General Store", gstin="29ABCDE1234F1Z5", registered_address="12 MG Road, Bengaluru",
            state="Karnataka", state_code="29")
FOREIGN_SHOP_TEXT = ["DIVYA", "9930008633", "divyaenterprises", "MALAD", "27ECNPS6389P1Z5", "Maharashtra"]


class ShopFixture:
    @classmethod
    def make_stock(cls):
        cls.admin = User.objects.create_user(username="shop-admin", password="Pass-12345!", role="admin")
        cls.tax = TaxRate.objects.create(name="GST 5% SD", rate=D("5.00"))
        cls.product = Product.objects.create(name="SD Biscuits", base_unit=Product.UNIT_PIECE, tax=cls.tax, mrp=D("20.00"))
        supplier = Supplier.objects.create(name="SD Supplier", gstin="29AAACA1234A1Z5", state="Karnataka", state_code="29")
        create_purchase(supplier=supplier, warehouse=get_default_warehouse(), invoice_date=timezone.localdate(),
                        line_items=[{"product": cls.product, "quantity": D("50"), "rate": D("10.00")}],
                        created_by=cls.admin, post=True)
        cls.customer = Customer.objects.create(name="SD Customer", state="Karnataka", state_code="29")

    def line(self):
        return [{"product": self.product, "quantity": D("1"), "rate_charged": D("20.00"), "tax_rate": D("5.00")}]


class IncompleteProfileBlocksPostingTests(ShopFixture, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_stock()

    def assert_blocked(self, call):
        with self.assertRaises(serializers.ValidationError) as ctx:
            call()
        self.assertEqual(ctx.exception.detail["business_profile"][0], PROFILE_INCOMPLETE_MESSAGE)

    def test_no_profile_blocks_direct_posting_but_allows_drafts(self):
        self.assert_blocked(lambda: create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                                                   line_items=self.line()))
        self.assertFalse(Invoice.objects.exists())
        draft = create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                               line_items=self.line(), state=Invoice.STATE_DRAFT)
        self.assertEqual(draft.state, Invoice.STATE_DRAFT)

    def test_each_missing_field_blocks_posting_a_draft(self):
        for field in ("business_name", "registered_address", "gstin", "state", "state_code"):
            with self.subTest(missing=field):
                BusinessProfile.objects.all().delete()
                BusinessProfile.objects.create(**{**SHOP, field: "  "})
                draft = create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                                       line_items=self.line(), state=Invoice.STATE_DRAFT)
                self.assert_blocked(lambda: post_invoice(invoice_id=draft.pk, posted_by=self.admin))
                self.assertEqual(Invoice.objects.get(pk=draft.pk).state, Invoice.STATE_DRAFT)

    def test_complete_profile_posts(self):
        BusinessProfile.objects.create(**SHOP)
        draft = create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                               line_items=self.line(), state=Invoice.STATE_DRAFT)
        self.assertEqual(post_invoice(invoice_id=draft.pk, posted_by=self.admin).state, Invoice.STATE_POSTED)

    def test_api_returns_the_message(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post("/api/invoices/", {
            "customer": self.customer.pk, "payment_type": "credit", "tax_mode": "exclusive",
            "line_items": [{"product": self.product.pk, "quantity": "1", "rate_charged": "20.00", "tax_rate": "5.00"}],
        }, format="json", HTTP_IDEMPOTENCY_KEY="sd-blocked-1")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["business_profile"][0], PROFILE_INCOMPLETE_MESSAGE)


class NoHardCodedShopDetailsTests(ShopFixture, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_stock()
        cls.profile = BusinessProfile.objects.create(**SHOP)  # no phone, email or terms
        cls.invoice = create_invoice(customer=cls.customer, created_by=cls.admin, payment_type="credit",
                                     line_items=[{"product": cls.product, "quantity": D("1"), "rate_charged": D("20.00"),
                                                  "tax_rate": D("5.00")}])

    def pdf_text(self, invoice):
        return pymupdf.open("pdf", build_invoice_a5_pdf(invoice))[0].get_text()

    def test_pdf_prints_only_the_profile_and_no_fallbacks(self):
        text = self.pdf_text(self.invoice)
        self.assertIn("SHARMA GENERAL STORE", text)
        self.assertIn("29ABCDE1234F1Z5", text)
        for foreign in FOREIGN_SHOP_TEXT:
            self.assertNotIn(foreign.lower(), text.lower())
        self.assertNotIn("Phone:", text)
        self.assertNotIn("E-Mail:", text)
        self.assertNotIn("Goods once sold", text)  # no built-in terms

    def test_draft_without_any_profile_prints_blanks_not_another_shop(self):
        draft = create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                               line_items=self.line(), state=Invoice.STATE_DRAFT)
        BusinessProfile.objects.all().delete()
        draft.seller_business_name_snapshot = ""
        text = self.pdf_text(draft)
        for foreign in FOREIGN_SHOP_TEXT:
            self.assertNotIn(foreign.lower(), text.lower())

    def test_customer_without_state_is_shown_in_the_sellers_state(self):
        walk_in = create_invoice(customer=None, created_by=self.admin, payment_type="cash", line_items=self.line())
        text = self.pdf_text(walk_in)
        self.assertIn("State: Karnataka (29)", text)
        self.assertIn("Place of Supply: 29 - Karnataka", text)
        self.assertNotIn("Maharashtra", text)

    def test_sixty_character_business_name_in_header_is_not_cut(self):
        name = "Shree Siddhivinayak Wholesale Provision Traders and Sons LLP"
        self.assertEqual(len(name), 60)
        self.invoice.seller_business_name_snapshot = name  # in memory only
        page = pymupdf.open("pdf", build_invoice_a5_pdf(self.invoice))[0]
        self.assertIn(name.upper(), " ".join(page.get_text().split()))
        tax_invoice = next(w for w in page.get_text("words") if w[4] == "TAX")
        header_words = [w for w in page.get_text("words") if w[4].isupper() and w[3] < tax_invoice[3] + 25 and w[0] < tax_invoice[0]]
        self.assertLess(max(w[2] for w in header_words), tax_invoice[0] - 2)  # stays in the seller column

    def test_header_name_layout(self):
        self.assertEqual(layout_header_name("Sharma General Store", 290)["font_size"], 11.0)
        long_name = layout_header_name("Shree Siddhivinayak Wholesale Provision Traders and Sons LLP", 270)
        self.assertFalse(long_name["truncated"])
        self.assertLessEqual(len(long_name["lines"]), 2)
        self.assertEqual(" ".join(long_name["lines"]), "SHREE SIDDHIVINAYAK WHOLESALE PROVISION TRADERS AND SONS LLP")
        self.assertGreaterEqual(long_name["font_size"], 8.0)

    def test_item_summary_excel_and_print_use_the_profile_name(self):
        summary = build_selected_invoices_item_summary([self.invoice.pk])
        self.assertEqual(summary["business_name"], "Sharma General Store")
        sheet = openpyxl.load_workbook(BytesIO(build_item_summary_xlsx(summary))).active
        self.assertEqual(sheet["A1"].value, "Sharma General Store")

    def test_sales_gst_report_uses_the_profile_name_or_blank(self):
        today = timezone.localdate()
        data = get_sales_gst_report_data(today, today)
        self.assertEqual(data["seller"]["business_name"], "Sharma General Store")
        BusinessProfile.objects.all().delete()
        data = get_sales_gst_report_data(today, today)
        self.assertEqual(data["seller"]["business_name"], "")
        sheet = openpyxl.load_workbook(BytesIO(build_sales_gst_report_xlsx(data))).active
        self.assertIn(sheet["A1"].value, ("", None))

    def test_new_profiles_have_no_built_in_terms(self):
        self.assertEqual(BusinessProfile._meta.get_field("terms_and_conditions").default, "")
        self.assertEqual(BusinessProfile(business_name="X").terms_and_conditions, "")
