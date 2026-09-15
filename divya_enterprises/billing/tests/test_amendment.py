from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase
from billing.models import AuditLog, Invoice, Payment, BusinessProfile
from billing.services import (
    amend_invoice,
    check_invoice_correction_eligibility,
    create_invoice,
    create_payment,
)
from customers.models import Customer
from inventory.models import Product, StockLedger, TaxRate


def _bp():
    return BusinessProfile.objects.get_or_create(
        defaults=dict(
            business_name="Amend Test Co", gstin="29AMEND1234A1Z5",
            registered_address="Street 1", state="Karnataka", state_code="29",
        )
    )[0]


def _make_user(username, role="admin"):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@t.local", password="P123!", role=role
    )


def _make_product(name, tax, stock=100):
    return Product.objects.create(
        name=name, unit_type="piece", unit_conversion_factor=1,
        default_price=100, cost_price=60, tax=tax, current_stock=stock,
    )


def _make_customer(name, n):
    return Customer.objects.create(
        name=name, contact_info=str(n), customer_type="B2C", is_regular=True, state_code="29",
    )


def _credit_inv(num, product, customer, user, qty=2):
    return create_invoice(
        customer=customer, invoice_number=num, notes="", created_by=user, payment_type="credit",
        line_items=[{"product": product, "quantity": Decimal(str(qty)), "rate_charged": Decimal("100"),
                     "tax_rate": Decimal("18"), "discount_amount": Decimal("0"),
                     "sales_unit_name": "piece", "conversion_factor": Decimal("1")}],
        state=Invoice.STATE_POSTED, place_of_supply="29",
    )


def _amend_inv(inv_pk, product, customer, user, qty=2, new_num="REPLACE-X"):
    return amend_invoice(
        invoice_id=inv_pk,
        corrected_line_items=[{"product": product, "quantity": Decimal(str(qty)), "rate_charged": Decimal("100"),
                               "tax_rate": Decimal("18"), "discount_amount": Decimal("0"),
                               "sales_unit_name": "piece", "conversion_factor": Decimal("1")}],
        customer=customer, payment_type="credit", notes="", place_of_supply="29",
        new_invoice_number=new_num, amended_by=user, reason="test reason",
    )


class DraftEditTests(APITestCase):
    def setUp(self):
        self.user = _make_user("de_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.c1 = _make_customer("DC1", 90001)
        self.c2 = _make_customer("DC2", 90002)
        self.tax = TaxRate.objects.create(name="18de", rate=Decimal("18.00"))
        _bp()

    def _p(self, name, stock=50):
        return _make_product(name, self.tax, stock)

    def _post_draft(self, product, qty=2, cid=None, pt="cash", inv_num=None):
        return self.client.post("/api/invoices/drafts/", {
            "invoice_number": inv_num or f"DR-{product.pk}",
            "customer": cid, "payment_type": pt,
            "line_items": [{"product": product.pk, "quantity": str(qty), "rate_charged": "80.00", "tax_rate": "18.00"}],
            "place_of_supply": "29", "tax_mode": "exclusive",
        }, format="json")

    def _patch_draft(self, draft_id, product, qty=3, cid=None, pt="cash", rate="80.00"):
        return self.client.patch(f"/api/invoices/{draft_id}/draft/", {
            "customer": cid, "payment_type": pt,
            "line_items": [{"product": product.pk, "quantity": str(qty), "rate_charged": rate, "tax_rate": "18.00"}],
            "place_of_supply": "29",
        }, format="json")

    def test_draft_can_be_edited(self):
        p = self._p("EditA"); r = self._post_draft(p)
        self.assertEqual(r.status_code, 201)
        p2 = self._p("EditB"); r2 = self._patch_draft(r.data["id"], p2, qty=5)
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(r2.data["line_items"][0]["product"], p2.pk)

    def test_draft_qty_and_rate_updated(self):
        p = self._p("QtyP"); r = self._post_draft(p, qty=1)
        r2 = self._patch_draft(r.data["id"], p, qty=7, rate="200.00")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(Decimal(r2.data["line_items"][0]["rate_charged"]), Decimal("200.00"))
        self.assertEqual(Decimal(r2.data["line_items"][0]["quantity"]), Decimal("7.000"))

    def test_draft_customer_changed(self):
        p = self._p("CustP")
        r = self._post_draft(p, cid=self.c1.pk, pt="credit", inv_num="DR-CUST-1")
        self.assertEqual(r.data["customer"], self.c1.pk)
        r2 = self._patch_draft(r.data["id"], p, cid=self.c2.pk, pt="credit")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["customer"], self.c2.pk)
        self.assertEqual(r2.data["customer_name_snapshot"], self.c2.name)

    def test_draft_does_not_deduct_stock(self):
        p = self._p("NoStock", stock=20)
        r = self._post_draft(p, qty=10); did = r.data["id"]
        before = Product.objects.get(pk=p.pk).current_stock
        self._patch_draft(did, p, qty=15)
        self.assertEqual(Product.objects.get(pk=p.pk).current_stock, before)
        self.assertFalse(StockLedger.objects.filter(reference_type="invoice", reference_id=did).exists())

    def test_draft_does_not_create_payment(self):
        p = self._p("NoPay"); r = self._post_draft(p); did = r.data["id"]
        self._patch_draft(did, p, qty=3)
        self.assertFalse(Payment.objects.filter(invoice_id=did).exists())

    def test_patch_posted_invoice_draft_returns_400(self):
        p = self._p("PostPatch", stock=10)
        r = self.client.post("/api/invoices/", {
            "invoice_number": "POST-PTEST-DE1", "customer": None, "payment_type": "cash",
            "line_items": [{"product": p.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "18.00"}],
            "place_of_supply": "29",
        }, format="json")
        r2 = self._patch_draft(r.data["id"], p, qty=2)
        self.assertEqual(r2.status_code, 400)

    def test_draft_edit_creates_audit_log(self):
        p = self._p("AuditDraft"); r = self._post_draft(p); did = r.data["id"]
        before = AuditLog.objects.filter(entity_type="Invoice", entity_id=did, action="invoice_draft_updated").count()
        self._patch_draft(did, p, qty=3)
        after = AuditLog.objects.filter(entity_type="Invoice", entity_id=did, action="invoice_draft_updated").count()
        self.assertEqual(after, before + 1)

    def test_draft_rate_is_per_piece(self):
        p = self._p("PerPiece"); r = self._post_draft(p, qty=1, inv_num="DR-PP-1")
        r2 = self._patch_draft(r.data["id"], p, qty=3, rate="7.35")
        self.assertEqual(r2.status_code, 200)
        self.assertAlmostEqual(float(r2.data["line_items"][0]["taxable_value_snapshot"]), 3 * 7.35, places=2)


class EligibilityTests(APITestCase):
    def setUp(self):
        self.user = _make_user("el_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.cust = _make_customer("ElCust", 90003)
        self.tax = TaxRate.objects.create(name="18el", rate=Decimal("18.00"))
        _bp()

    def _p(self, name, stock=100):
        return _make_product(name, self.tax, stock)

    def _inv(self, num, product, qty=2):
        return _credit_inv(num, product, self.cust, self.user, qty)

    def test_clean_invoice_eligible(self):
        p = self._p("ElP1"); inv = self._inv("EL-001", p)
        ok, reason = check_invoice_correction_eligibility(inv.pk)
        self.assertTrue(ok); self.assertEqual(reason, "")

    def test_eligibility_api_true(self):
        p = self._p("ElP2"); inv = self._inv("EL-002", p)
        r = self.client.get(f"/api/invoices/{inv.pk}/correction-eligibility/")
        self.assertEqual(r.status_code, 200); self.assertTrue(r.data["eligible"])

    def test_payment_blocks_eligibility(self):
        p = self._p("ElP3"); inv = self._inv("EL-003", p)
        create_payment(customer=None, invoice=inv, amount=inv.total_amount, actor=self.user)
        ok, reason = check_invoice_correction_eligibility(inv.pk)
        self.assertFalse(ok); self.assertIn("payment", reason.lower())

    def test_payment_blocks_eligibility_api(self):
        p = self._p("ElP4"); inv = self._inv("EL-004", p)
        create_payment(customer=None, invoice=inv, amount=inv.total_amount, actor=self.user)
        r = self.client.get(f"/api/invoices/{inv.pk}/correction-eligibility/")
        self.assertFalse(r.data["eligible"]); self.assertIn("payment", r.data["reason"].lower())

    def test_credit_note_blocks_eligibility(self):
        from billing.services import create_credit_note
        p = self._p("ElP5"); inv = self._inv("EL-005", p, qty=5)
        orig_line = inv.line_items.first()
        create_credit_note(original_invoice=inv, reason="ret", created_by=self.user,
            line_items=[{"product": p, "invoice_line_item": orig_line, "quantity": Decimal("1"), "sales_unit_name": "piece"}])
        ok, reason = check_invoice_correction_eligibility(inv.pk)
        self.assertFalse(ok); self.assertIn("credit note", reason.lower())

    def test_cancelled_invoice_not_eligible(self):
        from billing.services import cancel_invoice
        p = self._p("ElP6"); inv = self._inv("EL-006", p)
        cancel_invoice(invoice_id=inv.pk, cancelled_by=self.user, reason="test")
        ok, reason = check_invoice_correction_eligibility(inv.pk)
        self.assertFalse(ok); self.assertIn("cancelled", reason.lower())

    def test_already_amended_not_eligible(self):
        p = self._p("ElP7", stock=200); inv = self._inv("EL-007", p, qty=2)
        _amend_inv(inv.pk, p, self.cust, self.user, qty=1, new_num="EL-REPLACE-007")
        ok, reason = check_invoice_correction_eligibility(inv.pk)
        self.assertFalse(ok); self.assertIn("replacement", reason.lower())


class AmendmentWorkflowTests(APITestCase):
    def setUp(self):
        self.user = _make_user("aw_admin")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.cust = _make_customer("AWCust", 90004)
        self.tax = TaxRate.objects.create(name="18aw", rate=Decimal("18.00"))
        _bp()

    def _p(self, name, stock=100):
        return _make_product(name, self.tax, stock)

    def _inv(self, num, product, qty=3):
        return _credit_inv(num, product, self.cust, self.user, qty)

    def _amend(self, inv, product, qty=2, new_num="REPLACE-X"):
        return _amend_inv(inv.pk, product, self.cust, self.user, qty, new_num)

    def test_replacement_gets_new_number(self):
        p = self._p("NNP"); inv = self._inv("AW-001", p)
        orig, repl = self._amend(inv, p, new_num="AW-REPLACE-001")
        self.assertEqual(orig.invoice_number, "AW-001")
        self.assertEqual(repl.invoice_number, "AW-REPLACE-001")
        self.assertNotEqual(orig.pk, repl.pk)

    def test_original_cancelled_and_preserved(self):
        p = self._p("OrigP"); inv = self._inv("AW-002", p, qty=4); ot = inv.total_amount
        orig, repl = self._amend(inv, p, qty=2, new_num="AW-REPLACE-002")
        self.assertEqual(orig.state, Invoice.STATE_CANCELLED)
        self.assertIsNotNone(orig.cancelled_at)
        self.assertEqual(orig.total_amount, ot)

    def test_links_set_on_both_invoices(self):
        p = self._p("LinkP"); inv = self._inv("AW-003", p)
        orig, repl = self._amend(inv, p, new_num="AW-REPLACE-003")
        orig.refresh_from_db(); repl.refresh_from_db()
        self.assertEqual(orig.replacement_invoice_id, repl.pk)
        self.assertEqual(repl.amended_from_invoice_id, orig.pk)

    def test_stock_reversal_and_deduction(self):
        p = self._p("StockP", stock=50); inv = self._inv("AW-004", p, qty=5)
        self.assertEqual(Product.objects.get(pk=p.pk).current_stock, Decimal("45.000"))
        self._amend(inv, p, qty=3, new_num="AW-REPLACE-004")
        self.assertEqual(Product.objects.get(pk=p.pk).current_stock, Decimal("47.000"))

    def test_audit_log_links_both(self):
        p = self._p("AuditP"); inv = self._inv("AW-005", p)
        orig, repl = self._amend(inv, p, new_num="AW-REPLACE-005")
        log = AuditLog.objects.filter(action="invoice_amended", entity_id=orig.pk).last()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata["original_invoice_id"], orig.pk)
        self.assertEqual(log.metadata["replacement_invoice_id"], repl.pk)
        self.assertEqual(log.metadata["reason"], "test reason")

    def test_no_duplicate_replacement_via_api(self):
        p = self._p("IdempP", stock=200); inv = self._inv("AW-006", p, qty=2)
        payload = {"reason": "fix", "invoice_number": "AW-REPLACE-006", "customer": self.cust.pk,
                   "payment_type": "credit",
                   "line_items": [{"product": p.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "18.00"}],
                   "place_of_supply": "29"}
        r1 = self.client.post(f"/api/invoices/{inv.pk}/amend/", payload, format="json")
        self.assertEqual(r1.status_code, 201)
        payload["invoice_number"] = "AW-REPLACE-006B"
        r2 = self.client.post(f"/api/invoices/{inv.pk}/amend/", payload, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_amend_blocked_for_staff(self):
        p = self._p("StaffP", stock=50); inv = self._inv("AW-007", p)
        su = _make_user("st_amend_aw", role="staff")
        self.client.force_authenticate(su)
        r = self.client.post(f"/api/invoices/{inv.pk}/amend/",
            {"reason": "x", "invoice_number": "X", "customer": self.cust.pk, "payment_type": "credit",
             "line_items": [{"product": p.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "18.00"}],
             "place_of_supply": "29"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_amend_blocked_when_cash_payment_exists(self):
        p = self._p("CashP", stock=50)
        ci = create_invoice(customer=None, invoice_number="AW-CASH-001", notes="", created_by=self.user,
            payment_type="cash",
            line_items=[{"product": p, "quantity": Decimal("2"), "rate_charged": Decimal("100"),
                         "tax_rate": Decimal("18"), "discount_amount": Decimal("0"),
                         "sales_unit_name": "piece", "conversion_factor": Decimal("1")}],
            state=Invoice.STATE_POSTED, place_of_supply="29")
        self.assertTrue(Payment.objects.filter(invoice=ci).exists())
        r = self.client.post(f"/api/invoices/{ci.pk}/amend/",
            {"reason": "blocked", "invoice_number": "BLKD-001",
             "line_items": [{"product": p.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "18.00"}],
             "place_of_supply": "29"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("payment", str(r.data).lower())

    def test_serializer_exposes_amendment_fields(self):
        p = self._p("SerP", stock=100); inv = self._inv("AW-008", p, qty=2)
        orig, repl = self._amend(inv, p, qty=1, new_num="AW-REPLACE-008")
        r1 = self.client.get(f"/api/invoices/{orig.pk}/")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["replacement_invoice"], repl.pk)
        self.assertEqual(r1.data["replacement_invoice_number"], "AW-REPLACE-008")
        r2 = self.client.get(f"/api/invoices/{repl.pk}/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["amended_from_invoice"], orig.pk)
        self.assertEqual(r2.data["amended_from_invoice_number"], "AW-008")

    def test_amend_api_requires_reason(self):
        p = self._p("ValP", stock=50); inv = self._inv("AW-009", p)
        r = self.client.post(f"/api/invoices/{inv.pk}/amend/",
            {"line_items": [{"product": p.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "18.00"}],
             "place_of_supply": "29"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.data)
