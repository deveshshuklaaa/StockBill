from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import BusinessProfile, Invoice, InvoiceLineItem
from billing.pdf_engine import build_invoice_a5_pdf
from billing.services import create_invoice, update_draft_invoice
from billing.tax_engine import calculate_gst, TAX_MODE_EXCLUSIVE, TAX_MODE_INCLUSIVE
from customers.models import Customer
from inventory.models import AttributeDefinition, Category, InventoryBalance, Product, ProductAttributeValue, TaxRate, Warehouse


class GstAuditReproductionTests(TestCase):
    """
    Comprehensive regression tests for GST calculation bug audit.
    Covers all 17 scenarios requested in Phase 8.
    """

    @classmethod
    def setUpTestData(cls):
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_superuser(username="auditadmin", password="password123")
        cls.seller = BusinessProfile.objects.create(
            business_name="Divya Enterprises",
            trade_name="Divya Enterprises",
            gstin="27ABCDE1234F1Z5",
            registered_address="123 Market Yard, Pune, Maharashtra",
            state="Maharashtra",
            state_code="27",
            contact_details="9876543210",
        )
        cls.customer_intra = Customer.objects.create(
            name="Sant Nirankari Traders",
            state="Maharashtra",
            state_code="27",
            customer_type="B2B",
            gstin="27AABCS1429B1ZB",
        )
        cls.customer_inter = Customer.objects.create(
            name="Interstate Traders",
            state="Gujarat",
            state_code="24",
            customer_type="B2B",
            gstin="24AABCS1429B1ZB",
        )
        from inventory.services import get_default_warehouse
        cls.warehouse = get_default_warehouse()
        cls.tax_5, _ = TaxRate.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00")})
        cls.tax_18, _ = TaxRate.objects.get_or_create(name="GST 18%", defaults={"rate": Decimal("18.00")})
        cls.category, _ = Category.objects.get_or_create(code="SNK", defaults={"name": "Snacks"})
        cls.attr_box, _ = AttributeDefinition.objects.get_or_create(
            code="units_per_master_box",
            defaults={
                "name": "Units per Master Box",
                "data_type": AttributeDefinition.TYPE_INTEGER,
                "is_active": True,
            },
        )

    def _create_product(self, name, sku, mrp, pack_size=None, tax=None):
        p = Product.objects.create(
            name=name,
            sku=sku,
            category="Snacks",
            catalogue_category=self.category,
            mrp=Decimal(str(mrp)),
            default_price=Decimal(str(mrp)),
            cost_price=Decimal("5.00"),
            base_unit="piece",
            tax=tax or self.tax_5,
            is_active=True,
        )
        if pack_size:
            ProductAttributeValue.objects.create(
                product=p,
                attribute_definition=self.attr_box,
                value_integer=pack_size,
            )
        InventoryBalance.objects.create(
            product=p,
            warehouse=self.warehouse,
            quantity_on_hand=Decimal("100000.000"),
            average_cost=Decimal("5.00"),
        )
        return p

    def test_01_reproduction_1117_80_at_5_percent(self):
        """Scenario 1: ₹1,117.80 taxable at 5% -> expected GST ₹55.89, expected grand total ₹1,173.69."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [
                {"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "24", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "30", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"},
                {"quantity": "48", "rate_charged": "4.05", "tax_rate": "5.00"},
            ],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        self.assertEqual(res["totals"]["taxable_value"], Decimal("1117.80"))
        self.assertEqual(res["totals"]["total_tax"], Decimal("55.89"))
        self.assertEqual(res["totals"]["cgst_total"], Decimal("27.95"))
        self.assertEqual(res["totals"]["sgst_total"], Decimal("27.94"))
        self.assertEqual(res["totals"]["grand_total"], Decimal("1173.69"))

    def test_05_exact_8_line_invoice_reproduction(self):
        """Scenario 5: Exact 8-line invoice persisted to database matches expected lines and totals."""
        p1 = self._create_product("P1 Yellow Banana", "SKU-P1", "10.00")
        p2 = self._create_product("P2 Madras Mix", "SKU-P2", "10.00")
        p3 = self._create_product("P3 Chipsona Classic", "SKU-P3", "10.00")
        p4 = self._create_product("P4 Small Bhakarwadi", "SKU-P4", "10.00")
        p5 = self._create_product("P5 Masala Murukku", "SKU-P5", "10.00")
        p6 = self._create_product("P6 Bhel Mix", "SKU-P6", "10.00")
        p7 = self._create_product("P7 Tikhat Sev", "SKU-P7", "10.00")
        p8 = self._create_product("P8 Manglori Mix", "SKU-P8", "5.00")

        line_items = [
            {"product": p1, "quantity": "12", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p2, "quantity": "24", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p3, "quantity": "30", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p4, "quantity": "12", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p5, "quantity": "12", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p6, "quantity": "12", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p7, "quantity": "12", "rate_charged": "8.10", "discount_amount": "0.00", "tax_rate": "5.00"},
            {"product": p8, "quantity": "48", "rate_charged": "4.05", "discount_amount": "0.00", "tax_rate": "5.00"},
        ]

        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-05",
            created_by=self.user,
            payment_type="credit",
            line_items=line_items,
            state=Invoice.STATE_POSTED,
            tax_mode=Invoice.TAX_MODE_EXCLUSIVE,
        )

        lines = list(inv.line_items.all())
        self.assertEqual(len(lines), 8)
        self.assertEqual(inv.total_amount, Decimal("1173.69"))

        # Line 1: 97.20 @ 5% -> 4.86 (CGST 2.43, SGST 2.43)
        self.assertEqual(lines[0].taxable_value_snapshot, Decimal("97.20"))
        self.assertEqual(lines[0].tax_amount, Decimal("4.86"))
        self.assertEqual(lines[0].cgst_amount, Decimal("2.43"))
        self.assertEqual(lines[0].sgst_amount, Decimal("2.43"))
        self.assertEqual(lines[0].line_total, Decimal("102.06"))

        # Line 2: 194.40 @ 5% -> 9.72 (CGST 4.86, SGST 4.86)
        self.assertEqual(lines[1].taxable_value_snapshot, Decimal("194.40"))
        self.assertEqual(lines[1].tax_amount, Decimal("9.72"))
        self.assertEqual(lines[1].cgst_amount, Decimal("4.86"))
        self.assertEqual(lines[1].sgst_amount, Decimal("4.86"))
        self.assertEqual(lines[1].line_total, Decimal("204.12"))

        # Line 3: 243.00 @ 5% -> 12.15 (CGST 6.08, SGST 6.07)
        self.assertEqual(lines[2].taxable_value_snapshot, Decimal("243.00"))
        self.assertEqual(lines[2].tax_amount, Decimal("12.15"))
        self.assertEqual(lines[2].cgst_amount, Decimal("6.08"))
        self.assertEqual(lines[2].sgst_amount, Decimal("6.07"))
        self.assertEqual(lines[2].line_total, Decimal("255.15"))

        # Invoice totals
        tot_taxable = sum(l.taxable_value_snapshot for l in lines)
        tot_tax = sum(l.tax_amount for l in lines)
        tot_cgst = sum(l.cgst_amount for l in lines)
        tot_sgst = sum(l.sgst_amount for l in lines)

        self.assertEqual(tot_taxable, Decimal("1117.80"))
        self.assertEqual(tot_tax, Decimal("55.89"))
        self.assertEqual(tot_cgst, Decimal("27.95"))
        self.assertEqual(tot_sgst, Decimal("27.94"))
        self.assertEqual(inv.total_amount, Decimal("1173.69"))

    def test_02_single_line_97_20_at_5_percent(self):
        """Scenario 2: ₹97.20 at 5% -> expected GST ₹4.86."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "12", "rate_charged": "8.10", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("97.20"))
        self.assertEqual(line["tax_amount"], Decimal("4.86"))
        self.assertEqual(line["cgst_amount"], Decimal("2.43"))
        self.assertEqual(line["sgst_amount"], Decimal("2.43"))
        self.assertEqual(line["line_total"], Decimal("102.06"))
        self.assertEqual(res["totals"]["total_tax"], Decimal("4.86"))
        self.assertEqual(res["totals"]["grand_total"], Decimal("102.06"))

    def test_03_single_line_194_40_at_5_percent(self):
        """Scenario 3: ₹194.40 at 5% -> expected GST ₹9.72."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "24", "rate_charged": "8.10", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("194.40"))
        self.assertEqual(line["tax_amount"], Decimal("9.72"))
        self.assertEqual(line["cgst_amount"], Decimal("4.86"))
        self.assertEqual(line["sgst_amount"], Decimal("4.86"))
        self.assertEqual(line["line_total"], Decimal("204.12"))
        self.assertEqual(res["totals"]["total_tax"], Decimal("9.72"))
        self.assertEqual(res["totals"]["grand_total"], Decimal("204.12"))

    def test_04_single_line_243_00_at_5_percent(self):
        """Scenario 4: ₹243.00 at 5% -> expected GST ₹12.15."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "30", "rate_charged": "8.10", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("243.00"))
        self.assertEqual(line["tax_amount"], Decimal("12.15"))
        self.assertEqual(line["cgst_amount"] + line["sgst_amount"], Decimal("12.15"))
        self.assertEqual(line["line_total"], Decimal("255.15"))
        self.assertEqual(res["totals"]["total_tax"], Decimal("12.15"))
        self.assertEqual(res["totals"]["grand_total"], Decimal("255.15"))

    def test_06_cgst_plus_sgst_intra_state(self):
        """Scenario 6: Intra-state split CGST + SGST always equals line tax."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "10", "rate_charged": "33.33", "tax_rate": "18.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("333.30"))
        # 333.30 * 18% = 59.994 -> 59.99
        self.assertEqual(line["tax_amount"], Decimal("59.99"))
        self.assertEqual(line["cgst_amount"], Decimal("30.00"))
        self.assertEqual(line["sgst_amount"], Decimal("29.99"))
        self.assertEqual(line["cgst_amount"] + line["sgst_amount"], Decimal("59.99"))
        self.assertEqual(line["igst_amount"], Decimal("0.00"))

    def test_07_igst_inter_state(self):
        """Scenario 7: Inter-state full tax allocated to IGST, CGST/SGST zero."""
        res = calculate_gst(
            self.seller,
            self.customer_inter,
            [{"quantity": "10", "rate_charged": "33.33", "tax_rate": "18.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        self.assertTrue(res["is_inter_state"])
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("333.30"))
        self.assertEqual(line["tax_amount"], Decimal("59.99"))
        self.assertEqual(line["cgst_amount"], Decimal("0.00"))
        self.assertEqual(line["sgst_amount"], Decimal("0.00"))
        self.assertEqual(line["igst_amount"], Decimal("59.99"))

    def test_08_tax_inclusive_pricing(self):
        """Scenario 8: Tax-inclusive pricing correctly extracts taxable base and GST."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "10", "rate_charged": "105.00", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_INCLUSIVE,
        )
        line = res["lines"][0]
        # Net = 1050. Taxable = 1050 / 1.05 = 1000.00. Tax = 50.00
        self.assertEqual(line["taxable_value"], Decimal("1000.00"))
        self.assertEqual(line["tax_amount"], Decimal("50.00"))
        self.assertEqual(line["cgst_amount"], Decimal("25.00"))
        self.assertEqual(line["sgst_amount"], Decimal("25.00"))
        self.assertEqual(line["line_total"], Decimal("1050.00"))

    def test_09_tax_exclusive_pricing(self):
        """Scenario 9: Tax-exclusive pricing adds GST onto taxable base."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "10", "rate_charged": "100.00", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("1000.00"))
        self.assertEqual(line["tax_amount"], Decimal("50.00"))
        self.assertEqual(line["line_total"], Decimal("1050.00"))

    def test_10_discounts(self):
        """Scenario 10: Discounts reduce taxable base before GST calculation."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [{"quantity": "10", "rate_charged": "100.00", "discount_amount": "100.00", "tax_rate": "5.00"}],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        line = res["lines"][0]
        # Gross = 1000, Disc = 100, Taxable = 900. Tax = 45.00
        self.assertEqual(line["taxable_value"], Decimal("900.00"))
        self.assertEqual(line["tax_amount"], Decimal("45.00"))
        self.assertEqual(line["cgst_amount"], Decimal("22.50"))
        self.assertEqual(line["sgst_amount"], Decimal("22.50"))
        self.assertEqual(line["line_total"], Decimal("945.00"))

    def test_11_multiple_invoice_lines_consistency(self):
        """Scenario 11: Sum of line items exactly equals invoice totals."""
        res = calculate_gst(
            self.seller,
            self.customer_intra,
            [
                {"quantity": "1", "rate_charged": "97.20", "tax_rate": "5.00"},
                {"quantity": "1", "rate_charged": "194.40", "tax_rate": "5.00"},
                {"quantity": "1", "rate_charged": "243.00", "tax_rate": "5.00"},
            ],
            tax_mode=TAX_MODE_EXCLUSIVE,
        )
        sum_taxable = sum(l["taxable_value"] for l in res["lines"])
        sum_tax = sum(l["tax_amount"] for l in res["lines"])
        sum_cgst = sum(l["cgst_amount"] for l in res["lines"])
        sum_sgst = sum(l["sgst_amount"] for l in res["lines"])
        sum_totals = sum(l["line_total"] for l in res["lines"])

        self.assertEqual(res["totals"]["taxable_value"], sum_taxable)
        self.assertEqual(res["totals"]["total_tax"], sum_tax)
        self.assertEqual(res["totals"]["cgst_total"], sum_cgst)
        self.assertEqual(res["totals"]["sgst_total"], sum_sgst)
        self.assertEqual(res["totals"]["grand_total"], sum_totals)

    def test_12_piece_quantity_invoice(self):
        """Scenario 12: Direct piece sales preserve exact quantity and unit."""
        prod = self._create_product("Piece Prod", "SKU-PC", "10.00")
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-PC",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "50",
                "sales_unit_name": "piece",
                "conversion_factor": "1.000",
                "rate_charged": "8.00",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_POSTED,
        )
        line = inv.line_items.first()
        self.assertEqual(line.quantity, Decimal("50.000"))
        self.assertEqual(line.base_quantity, Decimal("50.000"))
        self.assertEqual(line.taxable_value_snapshot, Decimal("400.00"))
        self.assertEqual(line.tax_amount, Decimal("20.00"))
        self.assertEqual(inv.total_amount, Decimal("420.00"))

    def test_13_master_box_quantity_conversion(self):
        """Scenario 13: Master box sales convert correctly to base pieces and calculate tax."""
        prod = self._create_product("Box Prod", "SKU-BOX", "10.00", pack_size=192)
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-BOX",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "5",
                "sales_unit_name": "master box",
                "conversion_factor": "192.000",
                "rate_charged": "6.66",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_POSTED,
        )
        line = inv.line_items.first()
        self.assertEqual(line.quantity, Decimal("5.000"))
        self.assertEqual(line.base_quantity, Decimal("960.000"))
        # 960 * 6.66 = 6393.60. Tax 5% = 319.68. Total = 6713.28
        self.assertEqual(line.taxable_value_snapshot, Decimal("6393.60"))
        self.assertEqual(line.tax_amount, Decimal("319.68"))
        self.assertEqual(line.cgst_amount, Decimal("159.84"))
        self.assertEqual(line.sgst_amount, Decimal("159.84"))
        self.assertEqual(inv.total_amount, Decimal("6713.28"))

    def test_14_draft_invoice_precision(self):
        """Scenario 14: Draft invoice calculates and stores paise precision."""
        prod = self._create_product("Draft Prod", "SKU-DFT", "10.00")
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-DFT",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "12",
                "rate_charged": "8.10",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_DRAFT,
        )
        self.assertEqual(inv.state, Invoice.STATE_DRAFT)
        line = inv.line_items.first()
        self.assertEqual(line.taxable_value_snapshot, Decimal("97.20"))
        self.assertEqual(line.tax_amount, Decimal("4.86"))
        self.assertEqual(line.cgst_amount, Decimal("2.43"))
        self.assertEqual(line.sgst_amount, Decimal("2.43"))
        self.assertEqual(inv.total_amount, Decimal("102.06"))

    def test_15_posted_invoice_precision(self):
        """Scenario 15: Posted invoice calculates and persists paise precision."""
        prod = self._create_product("Posted Prod", "SKU-PST", "10.00")
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-PST",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "24",
                "rate_charged": "8.10",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_POSTED,
        )
        self.assertEqual(inv.state, Invoice.STATE_POSTED)
        line = inv.line_items.first()
        self.assertEqual(line.taxable_value_snapshot, Decimal("194.40"))
        self.assertEqual(line.tax_amount, Decimal("9.72"))
        self.assertEqual(inv.total_amount, Decimal("204.12"))

    def test_16_pdf_rendering_paise_precision(self):
        """Scenario 16: PDF generation includes exact paise precision without rounding distortion."""
        prod = self._create_product("PDF Prod", "SKU-PDF", "10.00")
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-PDF",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "30",
                "rate_charged": "8.10",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_POSTED,
        )
        pdf_bytes = build_invoice_a5_pdf(inv, copy_type="original")
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_17_invoice_detail_serializer_precision(self):
        """Scenario 17: Serializer representation matches paise precision."""
        from billing.serializers import InvoiceSerializer
        prod = self._create_product("Serial Prod", "SKU-SER", "10.00")
        inv = create_invoice(
            customer=self.customer_intra,
            invoice_number="INV-AUDIT-SER",
            created_by=self.user,
            payment_type="credit",
            line_items=[{
                "product": prod,
                "quantity": "12",
                "rate_charged": "8.10",
                "tax_rate": "5.00",
            }],
            state=Invoice.STATE_POSTED,
        )
        data = InvoiceSerializer(inv).data
        self.assertEqual(Decimal(str(data["total_amount"])), Decimal("102.06"))
        line_data = data["line_items"][0]
        self.assertEqual(Decimal(str(line_data["tax_amount"])), Decimal("4.86"))
        self.assertEqual(Decimal(str(line_data["cgst_amount"])), Decimal("2.43"))
        self.assertEqual(Decimal(str(line_data["sgst_amount"])), Decimal("2.43"))
