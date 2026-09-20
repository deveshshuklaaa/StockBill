from decimal import Decimal
from django.test import TestCase
from billing.tax_engine import calculate_gst, round_inr, round_paise, TAX_MODE_EXCLUSIVE, TAX_MODE_INCLUSIVE


class DummyProfile:
    def __init__(self, state_code):
        self.state_code = state_code


class TaxEngineTests(TestCase):

    def setUp(self):
        self.seller = DummyProfile("27")  # Maharashtra
        self.buyer_intra = DummyProfile("27")
        self.buyer_inter = DummyProfile("06")  # Haryana

    def test_intra_state_exclusive_computation(self):
        lines = [
            {"quantity": 2, "rate_charged": 1000, "discount_amount": 0, "tax_rate": 18}
        ]
        result = calculate_gst(self.seller, self.buyer_intra, lines, tax_mode=TAX_MODE_EXCLUSIVE)

        self.assertFalse(result["is_inter_state"])
        self.assertEqual(result["totals"]["subtotal"], Decimal("2000.00"))

        line = result["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("2000.00"))
        self.assertEqual(line["cgst_rate"], Decimal("9.00"))
        self.assertEqual(line["sgst_rate"], Decimal("9.00"))
        self.assertEqual(line["igst_rate"], Decimal("0.00"))
        self.assertEqual(line["cgst_amount"], Decimal("180"))
        self.assertEqual(line["sgst_amount"], Decimal("180"))
        self.assertEqual(line["igst_amount"], Decimal("0"))

        self.assertEqual(result["totals"]["grand_total"], Decimal("2360.00"))

    def test_inter_state_inclusive_computation(self):
        lines = [
            {"quantity": 1, "rate_charged": 1180, "discount_amount": 0, "tax_rate": 18}
        ]
        result = calculate_gst(self.seller, self.buyer_inter, lines, tax_mode=TAX_MODE_INCLUSIVE)

        self.assertTrue(result["is_inter_state"])

        line = result["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("1000.00"))  # 1180 / 1.18
        self.assertEqual(line["igst_rate"], Decimal("18.00"))
        self.assertEqual(line["cgst_amount"], Decimal("0"))
        self.assertEqual(line["sgst_amount"], Decimal("0"))
        self.assertEqual(line["igst_amount"], Decimal("180"))

        self.assertEqual(result["totals"]["grand_total"], Decimal("1180.00"))

    def test_discount_exclusion(self):
        lines = [
            {"quantity": 1, "rate_charged": 1000, "discount_amount": 100, "tax_rate": 18}
        ]
        result = calculate_gst(self.seller, self.buyer_intra, lines, tax_mode=TAX_MODE_EXCLUSIVE)

        line = result["lines"][0]
        self.assertEqual(line["taxable_value"], Decimal("900.00"))
        self.assertEqual(line["cgst_amount"], Decimal("81"))
        self.assertEqual(line["sgst_amount"], Decimal("81"))
        self.assertEqual(result["totals"]["grand_total"], Decimal("1062.00"))

    def test_rounding_paise_precision(self):
        # 116.67 at 18% = 21.0006 -> 21.00 total tax (10.50 CGST + 10.50 SGST)
        lines = [
            {"quantity": 1, "rate_charged": Decimal("116.67"), "tax_rate": 18}
        ]
        result = calculate_gst(self.seller, self.buyer_intra, lines, tax_mode=TAX_MODE_EXCLUSIVE)

        line = result["lines"][0]
        self.assertEqual(line["cgst_amount"], Decimal("10.50"))
        self.assertEqual(line["sgst_amount"], Decimal("10.50"))
        self.assertEqual(result["totals"]["total_tax"], Decimal("21.00"))
        self.assertEqual(line["line_total"], Decimal("137.67"))
