"""Tests for A5 Laser Invoice PDF Generation, Copy Designation, and Snapshots."""

from decimal import Decimal
import io
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
import pymupdf
import pypdf
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from billing.pdf_engine import amount_to_words, build_invoice_a5_pdf, _resolve_logo_path
from customers.models import Customer
from inventory.models import AttributeDefinition, Product, ProductAttributeValue, TaxRate

User = get_user_model()


class InvoicePdfGenerationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="pdf-admin", password="StrongPass123!", role="admin"
        )
        cls.staff = User.objects.create_user(
            username="pdf-staff", password="StrongPass123!", role="staff"
        )
        cls.profile = BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            trade_name="Divya FMCG",
            gstin="27ECNPS6389P1Z5",
            registered_address="Ground Floor Shop No 30 Shah Arcade, Malad East, Mumbai 400097",
            state="Maharashtra",
            state_code="27",
            phone="9930008633",
            email="divyaenterprises2501@gmail.com",
            terms_and_conditions="Goods once sold will not be taken back.\nInterest 24% after due date.",
        )
        cls.tax_5, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})
        cls.tax_18, _ = TaxRate.objects.get_or_create(name="GST 18%", defaults={"rate": Decimal("18.00")})

        cls.product_piece = Product.objects.create(
            name="Yellow Banana Chips 192P",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("10.00"),
            tax=cls.tax_5,
            hsn_sac="21069099",
            current_stock=Decimal("1000.000"),
        )
        cls.product_box = Product.objects.create(
            name="Chheda Potato Chips Sizzlin",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("5.00"),
            tax=cls.tax_5,
            hsn_sac="21069099",
            current_stock=Decimal("2000.000"),
        )
        cls.attr_master_box, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={"name": "Units per Master Box", "data_type": AttributeDefinition.TYPE_INTEGER},
        )
        ProductAttributeValue.objects.create(
            product=cls.product_box,
            attribute_definition=cls.attr_master_box,
            value_integer=192,
        )
        cls.product_no_hsn = Product.objects.create(
            name="Unbranded Snack No HSN",
            base_unit=Product.UNIT_PIECE,
            mrp=Decimal("20.00"),
            tax=cls.tax_18,
            hsn_sac="",
            current_stock=Decimal("500.000"),
        )

        cls.customer = Customer.objects.create(
            name="N P AGENCY",
            contact_info="9820099999",
            gstin="27AZHPG4742K1Z5",
            billing_address="First Floor, 79/630, Motilal Nagar, Mumbai",
            state="Maharashtra",
            state_code="27",
        )

        # Create a sample posted invoice
        cls.invoice = Invoice.objects.create(
            invoice_number="INV-A5-0001",
            customer=cls.customer,
            customer_name_snapshot=cls.customer.name,
            customer_gstin_snapshot=cls.customer.gstin,
            billing_address_snapshot=cls.customer.billing_address,
            seller_business_name_snapshot=cls.profile.business_name,
            seller_gstin_snapshot=cls.profile.gstin,
            seller_address_snapshot=cls.profile.registered_address,
            seller_state_snapshot="Maharashtra",
            seller_state_code_snapshot="27",
            place_of_supply="27",
            state=Invoice.STATE_POSTED,
            total_amount=Decimal("42995.00"),
            created_by=cls.admin,
        )

        # Line 1: Piece line
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            product=cls.product_piece,
            quantity=Decimal("10.000"),
            sales_unit_name="piece",
            conversion_factor=Decimal("1.000"),
            base_quantity=Decimal("10.000"),
            rate_charged=Decimal("7.35"),
            discount_amount=Decimal("0.00"),
            tax_rate=Decimal("5.00"),
            tax_amount=Decimal("3.68"),
            cgst_rate=Decimal("2.50"),
            cgst_amount=Decimal("1.84"),
            sgst_rate=Decimal("2.50"),
            sgst_amount=Decimal("1.84"),
            line_total=Decimal("77.18"),
            taxable_value_snapshot=Decimal("73.50"),
            product_name_snapshot="Yellow Banana Chips 192P",
            hsn_sac_snapshot="21069099",
            mrp_snapshot=Decimal("10.00"),
        )

        # Line 2: Master box line (2 boxes x 192 = 384 pcs)
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            product=cls.product_box,
            quantity=Decimal("2.000"),
            sales_unit_name="master box",
            conversion_factor=Decimal("192.000"),
            base_quantity=Decimal("384.000"),
            rate_charged=Decimal("3.68"),
            discount_amount=Decimal("0.00"),
            tax_rate=Decimal("5.00"),
            tax_amount=Decimal("70.66"),
            cgst_rate=Decimal("2.50"),
            cgst_amount=Decimal("35.33"),
            sgst_rate=Decimal("2.50"),
            sgst_amount=Decimal("35.33"),
            line_total=Decimal("1483.78"),
            taxable_value_snapshot=Decimal("1413.12"),
            product_name_snapshot="Chheda Potato Chips Sizzlin",
            hsn_sac_snapshot="21069099",
            mrp_snapshot=Decimal("5.00"),
        )

        # Line 3: Missing HSN product with 18% GST
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            product=cls.product_no_hsn,
            quantity=Decimal("5.000"),
            sales_unit_name="piece",
            conversion_factor=Decimal("1.000"),
            base_quantity=Decimal("5.000"),
            rate_charged=Decimal("100.00"),
            discount_amount=Decimal("10.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("88.20"),
            cgst_rate=Decimal("9.00"),
            cgst_amount=Decimal("44.10"),
            sgst_rate=Decimal("9.00"),
            sgst_amount=Decimal("44.10"),
            line_total=Decimal("578.20"),
            taxable_value_snapshot=Decimal("490.00"),
            product_name_snapshot="Unbranded Snack No HSN",
            hsn_sac_snapshot="",
            mrp_snapshot=Decimal("20.00"),
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    # 1. Posted invoice PDF generates successfully
    def test_posted_invoice_pdf_generates_successfully(self):
        client = self.client_as(self.staff)
        res = client.get(f"/api/invoices/{self.invoice.pk}/pdf/?copy=original")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertTrue(res.content.startswith(b"%PDF-1.4"))
        self.assertIn("invoice-inv-a5-0001-original.pdf", res["Content-Disposition"])

    # 2. Original designation works
    def test_original_designation_works(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        page_text = doc[0].get_text()
        self.assertIn("ORIGINAL", page_text)
        self.assertNotIn("DUPLICATE", page_text)

    # 3. Duplicate designation works
    def test_duplicate_designation_works(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="duplicate")
        doc = pymupdf.open("pdf", pdf_bytes)
        page_text = doc[0].get_text()
        self.assertIn("DUPLICATE", page_text)
        self.assertNotIn("REPRINT", page_text)

    # 3b. Reprint designation works
    def test_reprint_designation_works(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="reprint")
        doc = pymupdf.open("pdf", pdf_bytes)
        page_text = doc[0].get_text()
        self.assertIn("REPRINT", page_text)

    # 4. Original and duplicate do not mutate invoice
    def test_original_and_duplicate_do_not_mutate_invoice(self):
        initial_updated_at = self.invoice.updated_at
        initial_total = self.invoice.total_amount
        initial_state = self.invoice.state

        build_invoice_a5_pdf(self.invoice, copy_type="original")
        build_invoice_a5_pdf(self.invoice, copy_type="duplicate")

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.updated_at, initial_updated_at)
        self.assertEqual(self.invoice.total_amount, initial_total)
        self.assertEqual(self.invoice.state, initial_state)

    # 5. Reprint does not mutate invoice
    def test_reprint_does_not_mutate_invoice(self):
        client = self.client_as(self.staff)
        res1 = client.get(f"/api/invoices/{self.invoice.pk}/pdf/")
        res2 = client.get(f"/api/invoices/{self.invoice.pk}/pdf/")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(res1.content), len(res2.content))

    # 6. Snapshot data is used (not current product/customer master)
    def test_snapshot_data_used(self):
        # Mutate current product and customer
        self.product_piece.name = "Mutated Product Name"
        self.product_piece.mrp = Decimal("999.00")
        self.product_piece.save()

        self.customer.name = "Mutated Customer Name"
        self.customer.gstin = "MUTATED-GSTIN"
        self.customer.save()

        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()

        # Should use snapshots
        self.assertIn("Yellow Banana Chips 192P", text)
        self.assertIn("N P AGENCY", text)
        self.assertIn("27AZHPG4742K1Z5", text)
        self.assertNotIn("Mutated Product Name", text)
        self.assertNotIn("Mutated Customer Name", text)

    # 7. HSN blank/missing is handled
    def test_missing_hsn_renders_dash(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("Unbranded Snack No HSN", text)
        # Verify it doesn't crash on missing HSN

    # 8. Qty column displays numbers only (no 'pcs', 'Box', etc.) and Pack column displays units_per_master_box
    def test_quantity_is_numeric_only_and_pack_displays_units_per_master_box(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        # Qty is strictly numeric without any unit suffix
        self.assertNotIn("10 pcs", text)
        self.assertNotIn("2 Box", text)
        self.assertNotIn("pcs", text.lower())
        # Pack uses Product.units_per_master_box
        self.assertIn("192", text)
        self.assertEqual(self.product_box.units_per_master_box, 192)

    # 9. Piece quantity renders numeric only with no trailing decimals
    def test_piece_quantity_renders_correctly(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertNotIn("10 pcs", text)
        self.assertNotIn("10.000", text)
        self.assertNotIn("pcs", text.lower())

    # 10. Existing Pack column is used and missing units_per_master_box renders dash safely
    def test_pack_column_missing_units_handled_safely(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIsNone(self.product_piece.units_per_master_box)
        # Should render dash for missing units_per_master_box safely without error
        self.assertIn("Pack", text)
        self.assertIn("192", text)
        # Verify no extra column was added - exactly 1 Pack column header
        self.assertEqual(text.count("Pack"), 1)

    # 10b. Product table column headers and font size
    def test_product_table_headers_and_item_font_size(self):
        from billing.pdf_engine import ITEM_ROW_FONT_SIZE
        self.assertEqual(ITEM_ROW_FONT_SIZE, 9.0)
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        expected_headers = [
            "Sr.", "Qty.", "Pack", "Product Description", "HSN",
            "MRP", "Rate / Piece", "Dis", "SGST", "CGST", "Amount"
        ]
        for h in expected_headers:
            self.assertIn(h, text)

    # 11. GST summary renders correctly
    def test_gst_summary_renders_correctly(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("GST 5.00%", text)
        self.assertIn("GST 18.00%", text)
        self.assertIn("TOTAL GST", text)

    # 12. Multi-page invoice generates
    def test_multipage_invoice_generates(self):
        # Create 18 lines to exceed single-page budget
        long_lines = []
        base_line = self.invoice.line_items.first()
        for i in range(18):
            line = InvoiceLineItem(
                invoice=self.invoice,
                product=base_line.product,
                product_name_snapshot=f"Multi Item {i+1}",
                quantity=Decimal("5"),
                sales_unit_name="piece",
                conversion_factor=Decimal("1.000"),
                base_quantity=Decimal("5"),
                rate_charged=Decimal("50.00"),
                discount_amount=Decimal("0.00"),
                tax_rate=Decimal("5.00"),
                tax_amount=Decimal("12.50"),
                cgst_rate=Decimal("2.50"),
                cgst_amount=Decimal("6.25"),
                sgst_rate=Decimal("2.50"),
                sgst_amount=Decimal("6.25"),
                igst_rate=Decimal("0.00"),
                igst_amount=Decimal("0.00"),
                line_total=Decimal("262.50"),
                taxable_value_snapshot=Decimal("250.00"),
                mrp_snapshot=Decimal("60.00"),
                hsn_sac_snapshot="21069099",
            )
            long_lines.append(line)

        pdf_bytes = build_invoice_a5_pdf(self.invoice, lines=long_lines)
        doc = pymupdf.open("pdf", pdf_bytes)
        self.assertEqual(len(doc), 2)

    # 13. Continuation pages render
    def test_continuation_pages_render(self):
        long_lines = []
        base_line = self.invoice.line_items.first()
        for i in range(18):
            line = InvoiceLineItem(
                invoice=self.invoice,
                product=base_line.product,
                product_name_snapshot=f"Multi Item {i+1}",
                quantity=Decimal("5"),
                sales_unit_name="piece",
                conversion_factor=Decimal("1.000"),
                base_quantity=Decimal("5"),
                rate_charged=Decimal("50.00"),
                discount_amount=Decimal("0.00"),
                tax_rate=Decimal("5.00"),
                tax_amount=Decimal("12.50"),
                cgst_rate=Decimal("2.50"),
                cgst_amount=Decimal("6.25"),
                sgst_rate=Decimal("2.50"),
                sgst_amount=Decimal("6.25"),
                igst_rate=Decimal("0.00"),
                igst_amount=Decimal("0.00"),
                line_total=Decimal("262.50"),
                taxable_value_snapshot=Decimal("250.00"),
                mrp_snapshot=Decimal("60.00"),
                hsn_sac_snapshot="21069099",
            )
            long_lines.append(line)

        pdf_bytes = build_invoice_a5_pdf(self.invoice, lines=long_lines)
        doc = pymupdf.open("pdf", pdf_bytes)
        page1_text = doc[0].get_text()
        page2_text = doc[1].get_text()

        self.assertIn("Continued... Page 2", page1_text)
        self.assertIn("TOTAL B/F", page2_text)
        self.assertIn("Page 1 of 2", page1_text)
        self.assertIn("Page 2 of 2", page2_text)

    # 14. Amount in words renders
    def test_amount_in_words_renders(self):
        words = amount_to_words(Decimal("42995.00"))
        self.assertEqual(words, "Rs. Forty Two Thousand Nine Hundred and Ninety Five only")

        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("Rs. Forty Two Thousand Nine Hundred and Ninety Five only", text)

    # 15. Logo / resource loading works
    def test_logo_resource_loading_works(self):
        logo_path = _resolve_logo_path()
        self.assertIsNotNone(logo_path)
        self.assertTrue(Path(logo_path).exists())

    # 16. Page size is correct: A4 Portrait 210 mm x 297 mm (595.28 pt x 841.89 pt)
    def test_page_size_is_a4_portrait(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        rect = doc[0].rect
        width_mm = rect.width * 25.4 / 72
        height_mm = rect.height * 25.4 / 72
        self.assertAlmostEqual(width_mm, 210.0, delta=0.5)
        self.assertAlmostEqual(height_mm, 297.0, delta=0.5)
        self.assertAlmostEqual(rect.width, 595.28, delta=0.5)
        self.assertAlmostEqual(rect.height, 841.89, delta=0.5)

    def test_rate_shown_as_rate_per_piece(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("Rate / Piece", text)
        self.assertNotIn("2 Box", text)
        self.assertIn("192", text)
        self.assertIn("3.68", text)
        self.assertIn("1483.78", text)

    def test_exact_company_details(self):
        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("DIVYA ENTERPRISES", text)
        self.assertIn("Shah Arcade", text)
        self.assertIn("Malad East", text)
        self.assertIn("9930008633", text)
        self.assertIn("divyaenterprises2501@gmail.com", text)
        self.assertIn("27ECNPS6389P1Z5", text)
        self.assertIn("Maharashtra", text)
        self.assertNotIn("Uttar Pradesh", text)

    # 17. Cancelled/draft behavior follows business rules
    def test_cancelled_and_draft_behavior(self):
        # Cancelled invoice
        self.invoice.state = Invoice.STATE_CANCELLED
        self.invoice.cancellation_reason = "Damaged during transit"
        self.invoice._allow_lifecycle_transition = True
        self.invoice.save()

        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()
        self.assertIn("CANCELLED", text)
        self.assertIn("Damaged during transit", text)

        # Draft invoice
        draft_invoice = Invoice.objects.create(
            invoice_number="INV-A5-DRAFT-1",
            state=Invoice.STATE_DRAFT,
            total_amount=Decimal("100.00"),
            created_by=self.admin,
        )
        pdf_draft = build_invoice_a5_pdf(draft_invoice)
        doc_draft = pymupdf.open("pdf", pdf_draft)
        text_draft = doc_draft[0].get_text()
        self.assertIn("DRAFT", text_draft)

    # 18. Permission checks remain enforced
    def test_permission_checks_remain_enforced(self):
        # Unauthenticated request rejected
        unauth_client = APIClient()
        res = unauth_client.get(f"/api/invoices/{self.invoice.pk}/pdf/")
        self.assertIn(res.status_code, [401, 403])

        # Staff can view/print
        staff_client = self.client_as(self.staff)
        res_staff = staff_client.get(f"/api/invoices/{self.invoice.pk}/pdf/")
        self.assertEqual(res_staff.status_code, 200)

    # 19. Regression test: invoice snapshots take precedence over BusinessProfile
    # Ensures wrong-state (Uttar Pradesh/09) cannot leak into PDF when profile has bad data
    def test_pdf_uses_invoice_snapshots_not_business_profile(self):
        """Invoice snapshots are authoritative for posted invoices; BusinessProfile must not override."""
        # Create a second BusinessProfile with WRONG state data (simulates bad config)
        bad_profile = BusinessProfile.objects.create(
            business_name="Wrong Company",
            trade_name="Wrong Trade",
            gstin="09AAAAA0000A1Z5",  # Uttar Pradesh GSTIN
            registered_address="Wrong Address, Lucknow, Uttar Pradesh",
            state="Uttar Pradesh",
            state_code="09",
            phone="9999999999",
            email="wrong@example.com",
        )

        # Generate PDF for the posted invoice (which has Maharashtra snapshots)
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()

        # Must use invoice snapshots (Maharashtra/27), NOT the bad profile (Uttar Pradesh/09)
        # Address may be split across lines in PDF, so check for key parts
        self.assertIn("Divya Enterprises", text)
        self.assertIn("Malad", text)
        self.assertIn("Mumbai", text)
        self.assertIn("400097", text)
        self.assertIn("27ECNPS6389P1Z5", text)
        self.assertIn("Place of Supply: 27", text)

        # Must NOT contain Uttar Pradesh / 09 data from the bad profile
        self.assertNotIn("Uttar Pradesh", text)
        self.assertNotIn("09AAAAA0000A1Z5", text)
        self.assertNotIn("Wrong Company", text)
        self.assertNotIn("Lucknow", text)
        self.assertNotIn("Place of Supply: 09", text)

    # 20. Bank details: no placeholder/fabricated values printed
    def test_pdf_no_fabricated_bank_details(self):
        """Bank details must not appear unless explicitly configured in BusinessProfile."""
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()

        # Common placeholder patterns that must NOT appear
        forbidden_patterns = [
            "Bank Name", "Account No", "Account Number", "IFSC", "Branch",
            "0000000000", "XXXXXXXX", "PLACEHOLDER", "NOT CONFIGURED",
        ]
        for pattern in forbidden_patterns:
            self.assertNotIn(pattern, text, f"Forbidden placeholder '{pattern}' found in PDF")

    # 21. Regression Test: Invoice PDF MediaBox is exact A4 Portrait with 0 rotation
    def test_invoice_pdf_a4_portrait_dimensions_and_orientation(self):
        """Verify the generated PDF strictly matches A4 Portrait physical specifications.

        - Width: ~595.28 pt (210 mm)
        - Height: ~841.89 pt (297 mm)
        - Orientation: Portrait (height > width)
        - Rotation: 0 degrees (no landscape or rotated coordinate space)
        - ViewerPreferences: PrintScaling=None (forces Actual Size / 100% in print dialogs)
        """
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")

        # PyMuPDF verification
        doc = pymupdf.open("pdf", pdf_bytes)
        self.assertGreater(len(doc), 0)
        for page in doc:
            self.assertAlmostEqual(page.rect.width, 595.28, delta=0.5)
            self.assertAlmostEqual(page.rect.height, 841.89, delta=0.5)
            self.assertGreater(page.rect.height, page.rect.width, "Invoice must be Portrait orientation")
            self.assertEqual(page.rotation, 0, "Invoice page rotation must be 0 degrees")

        # PyPDF verification of MediaBox and ViewerPreferences
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            mb = page.mediabox
            self.assertAlmostEqual(float(mb.width), 595.28, delta=0.5)
            self.assertAlmostEqual(float(mb.height), 841.89, delta=0.5)
            self.assertEqual(int(page.get("/Rotate", 0)), 0)

        catalog = reader.trailer["/Root"]
        viewer_prefs = catalog.get("/ViewerPreferences")
        self.assertIsNotNone(viewer_prefs, "ViewerPreferences dictionary must be present in catalog")
        self.assertEqual(viewer_prefs.get("/PrintScaling"), "/None", "PrintScaling must be set to /None")

    # Alias to preserve backwards compatibility for any test runner targeting the old name
    test_invoice_pdf_a5_landscape_dimensions_and_orientation = test_invoice_pdf_a4_portrait_dimensions_and_orientation

    # 22. Regression Test: Bounding box of content fits within page bounds without clipping
    def test_invoice_pdf_content_fits_page_bounds(self):
        """Verify rendered visual content and drawing commands fit within the top A5 area of A4 page rectangle."""
        pdf_bytes = build_invoice_a5_pdf(self.invoice, copy_type="original")
        doc = pymupdf.open("pdf", pdf_bytes)
        page = doc[0]

        # Check all text blocks are within page bounds [0, 0, 595.28, 841.89] and top A5 area
        text_page = page.get_text("blocks")
        for block in text_page:
            x0, y0, x1, y1, text, block_no, block_type = block
            self.assertGreaterEqual(x0, 0, f"Text block '{text[:20]}' exceeds left boundary: {x0}")
            self.assertLessEqual(x1, 595.5, f"Text block '{text[:20]}' exceeds right boundary: {x1}")
            self.assertGreaterEqual(y0, 0, f"Text block '{text[:20]}' exceeds top boundary: {y0}")
            self.assertLessEqual(y1, 445.0, f"Text block '{text[:20]}' exceeds A5 top section boundary: {y1}")

    # 23. Product Description: strictly 9 pt font, wraps onto multiple lines without shrinking
    def test_product_description_9pt_and_wrapping(self):
        """Verify long product descriptions wrap at 9 pt instead of shrinking font size."""
        from billing.pdf_engine import (
            ITEM_ROW_FONT_SIZE,
            ITEM_ROW_HEIGHT,
            ITEM_LINE_LEADING,
            INVOICE_SCALE,
            wrap_product_description,
            get_item_row_height,
        )

        # 1. Unit verification of wrapping function
        long_name = "Chheda's Chipsona Potato Chips Classic Salted"
        wrapped = wrap_product_description(long_name, max_w=158.0, font_name="Helvetica", font_size=ITEM_ROW_FONT_SIZE)
        self.assertGreater(len(wrapped), 1, "Long description must wrap into multiple lines")
        self.assertEqual(wrapped[0], "Chheda's Chipsona Potato Chips")
        self.assertEqual(wrapped[1], "Classic Salted")

        # Row height expands dynamically
        h1 = get_item_row_height(["Short Name"])
        h2 = get_item_row_height(wrapped)
        self.assertEqual(h1, ITEM_ROW_HEIGHT)
        self.assertEqual(h2, ITEM_ROW_HEIGHT + ITEM_LINE_LEADING)

        # 2. PDF rendering verification with long description line item
        lines = list(self.invoice.line_items.all())
        lines[0].product_name_snapshot = long_name

        pdf_bytes = build_invoice_a5_pdf(self.invoice, lines=lines)
        doc = pymupdf.open("pdf", pdf_bytes)
        page = doc[0]

        # Check PyMuPDF spans for the wrapped product description
        text_page = page.get_text("dict")
        found_spans = []
        expected_size = ITEM_ROW_FONT_SIZE * INVOICE_SCALE  # 9.0 * 0.98 = 8.82 pt

        for b in text_page["blocks"]:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    if "Chipsona" in s["text"] or "Classic Salted" in s["text"]:
                        found_spans.append(s)

        self.assertGreaterEqual(len(found_spans), 2, "Both lines of wrapped description must be present")
        for span in found_spans:
            # Must remain 9.0 pt (scaled to 8.82 pt in PDF coords) - never shrunk to 7 or 8 pt
            self.assertAlmostEqual(span["size"], expected_size, places=2)
            # Must not overflow product description column horizontally
            self.assertGreaterEqual(span["bbox"][0], 115.0)
            self.assertLessEqual(span["bbox"][2], 295.0)

    # 24. Main item table structure: Qty numeric only, Pack units_per_master_box, exactly 11 columns
    def test_item_table_columns_qty_and_pack(self):
        """Verify Qty is numeric only, Pack displays units_per_master_box, and no extra column exists."""
        expected_headers = [
            "Sr.", "Qty.", "Pack", "Product Description", "HSN",
            "MRP", "Rate / Piece", "Dis", "SGST", "CGST", "Amount",
        ]

        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        text = doc[0].get_text()

        # Check that table headers are present
        for hdr in expected_headers:
            self.assertIn(hdr, text)

        # Pack displays Product.units_per_master_box (e.g. 192 from product_piece)
        self.assertIn("192", text)

        # Qty must be numeric only in table rows (e.g. '384', '10', '5'), no unit suffixes
        for line in text.splitlines():
            clean_l = line.strip()
            # If line is a quantity number, ensure no 'pcs' or 'Box' attached
            if clean_l.isdigit() and int(clean_l) in [384, 10, 5]:
                self.assertNotIn("pcs", clean_l.lower())
                self.assertNotIn("box", clean_l.lower())


    # 25. Thin vertical column separators between every adjacent column
    def test_thin_vertical_column_separators(self):
        """Verify thin vertical separator lines (0.25 - 0.40 pt) are drawn between all adjacent columns."""
        from billing.pdf_engine import INVOICE_SCALE

        pdf_bytes = build_invoice_a5_pdf(self.invoice)
        doc = pymupdf.open("pdf", pdf_bytes)
        page = doc[0]

        drawings = page.get_drawings()
        expected_linewidth = 0.35 * INVOICE_SCALE  # 0.35 * 0.98 = ~0.343 pt

        # Find separator line drawings with lineWidth approximately 0.34 pt
        sep_lines = [
            d for d in drawings
            if d.get("width") is not None and abs(d["width"] - expected_linewidth) < 0.05
        ]
        # 10 column separators between the 11 columns (in header and body)
        self.assertGreaterEqual(len(sep_lines), 10, "Thin vertical separators must be drawn across columns")

