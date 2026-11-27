"""Release A1: optional whole-bill round-off to the nearest rupee (ROUND_HALF_UP).

Only the invoice's final total is rounded. Lines, taxable value and GST stay
exact; round_off is fixed at posting with the Business Profile setting in
force then; credit notes completing a full reversal carry the invoice's
round_off so a fully credited invoice nets to exactly 0.
"""

import datetime
from decimal import Decimal

import pymupdf
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, CreditNote, Invoice, Payment
from billing.pdf_engine import amount_to_words, build_invoice_a5_pdf
from billing.reports import get_sales_gst_report_data
from billing.services import (
    _apply_round_off,
    amend_invoice,
    create_credit_note,
    create_invoice,
    post_invoice,
    update_draft_invoice,
)
from customers.models import Customer
from inventory.models import Product, Supplier, TaxRate
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse

User = get_user_model()
D = Decimal


class ApplyRoundOffTests(APITestCase):
    def test_half_up_to_the_rupee(self):
        cases = [
            ("107.10", "-0.10", "107.00"),
            ("107.50", "0.50", "108.00"),
            ("107.49", "-0.49", "107.00"),
            ("107.51", "0.49", "108.00"),
            ("108.00", "0.00", "108.00"),
            ("0.50", "0.50", "1.00"),
        ]
        for exact, round_off, total in cases:
            with self.subTest(exact=exact):
                self.assertEqual(_apply_round_off(D(exact), True), (D(round_off), D(total)))

    def test_setting_off_keeps_the_exact_total(self):
        self.assertEqual(_apply_round_off(D("107.10"), False), (D("0.00"), D("107.10")))

    def test_round_off_never_exceeds_fifty_paise(self):
        for paise in range(0, 300):
            exact = D(paise) / 100 + D("100")
            round_off, total = _apply_round_off(exact, True)
            self.assertLessEqual(abs(round_off), D("0.50"))
            self.assertEqual(total, exact + round_off)
            self.assertEqual(total, total.to_integral_value())


class RoundOffServiceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="ro-admin", password="Pass-12345!", role="admin")
        cls.staff = User.objects.create_user(username="ro-staff", password="Pass-12345!", role="staff")
        cls.profile = BusinessProfile.objects.create(
            business_name="RO Test Traders", gstin="27ABCDE1234F1Z5", registered_address="Mumbai",
            state="Maharashtra", state_code="27",
        )
        cls.tax_5 = TaxRate.objects.create(name="GST 5% RO", rate=D("5.00"))
        cls.tax_0 = TaxRate.objects.create(name="GST 0% RO", rate=D("0.00"))
        supplier = Supplier.objects.create(name="RO Supplier", gstin="27AAACA1234A1Z5", state="Maharashtra", state_code="27")
        cls.chips = Product.objects.create(name="RO Chips", base_unit=Product.UNIT_PIECE, tax=cls.tax_5, mrp=D("120.00"))
        cls.rice = Product.objects.create(name="RO Rice", base_unit=Product.UNIT_PIECE, tax=cls.tax_0, mrp=D("120.00"))
        create_purchase(
            supplier=supplier, warehouse=get_default_warehouse(), invoice_date=timezone.localdate(),
            line_items=[
                {"product": cls.chips, "quantity": D("100"), "rate": D("60.00")},
                {"product": cls.rice, "quantity": D("100"), "rate": D("60.00")},
            ],
            created_by=cls.admin, post=True,
        )
        cls.customer = Customer.objects.create(name="RO Customer", state_code="27", credit_limit=D("0"))

    def setUp(self):
        BusinessProfile.objects.filter(pk=self.profile.pk).update(round_off_invoice_total=True)

    def set_round_off(self, enabled):
        BusinessProfile.objects.filter(pk=self.profile.pk).update(round_off_invoice_total=enabled)

    def chips_line(self, qty="1", rate="102.00"):
        # 1 x 102.00 + 5% GST (2.55 + 2.55) = 107.10
        return {"product": self.chips, "quantity": D(qty), "rate_charged": D(rate), "tax_rate": D("5.00")}

    def rice_line(self, rate):
        return {"product": self.rice, "quantity": D("1"), "rate_charged": D(rate), "tax_rate": D("0.00")}

    def invoice(self, lines, payment_type="credit", state=Invoice.STATE_POSTED):
        return create_invoice(customer=self.customer, created_by=self.staff, payment_type=payment_type,
                              line_items=lines, state=state)

    # 1. Posted totals: 107.10 -> 107.00, 107.50 -> 108.00, 107.49 -> 107.00, exact rupee -> 0
    def test_posted_totals_round_half_up(self):
        cases = [
            ([self.chips_line()], "-0.10", "107.00"),
            ([self.rice_line("107.50")], "0.50", "108.00"),
            ([self.rice_line("107.49")], "-0.49", "107.00"),
            ([self.rice_line("108.00")], "0.00", "108.00"),
        ]
        for lines, round_off, total in cases:
            with self.subTest(total=total, round_off=round_off):
                inv = self.invoice(lines)
                inv.refresh_from_db()
                self.assertEqual(inv.round_off, D(round_off))
                self.assertEqual(inv.total_amount, D(total))
                exact = sum(line.line_total for line in inv.line_items.all())
                self.assertEqual(inv.total_amount, exact + inv.round_off)

    # 2. Setting off -> no round-off
    def test_setting_off_posts_the_exact_total(self):
        self.set_round_off(False)
        inv = self.invoice([self.chips_line()])
        inv.refresh_from_db()
        self.assertEqual((inv.round_off, inv.total_amount), (D("0.00"), D("107.10")))

    # 3. Round-off is fixed at posting with the setting in force then
    def test_draft_preview_is_recomputed_at_posting(self):
        draft = self.invoice([self.chips_line()], state=Invoice.STATE_DRAFT)
        draft.refresh_from_db()
        self.assertEqual((draft.round_off, draft.total_amount), (D("-0.10"), D("107.00")))  # preview
        self.set_round_off(False)
        posted = post_invoice(invoice_id=draft.pk, posted_by=self.staff)
        posted.refresh_from_db()
        self.assertEqual(posted.state, Invoice.STATE_POSTED)
        self.assertEqual((posted.round_off, posted.total_amount), (D("0.00"), D("107.10")))

    def test_setting_switched_on_before_posting_applies(self):
        self.set_round_off(False)
        draft = self.invoice([self.chips_line()], state=Invoice.STATE_DRAFT)
        self.assertEqual(Invoice.objects.get(pk=draft.pk).round_off, D("0.00"))
        self.set_round_off(True)
        posted = post_invoice(invoice_id=draft.pk, posted_by=self.staff)
        posted.refresh_from_db()
        self.assertEqual((posted.round_off, posted.total_amount), (D("-0.10"), D("107.00")))

    def test_updating_a_draft_refreshes_the_preview(self):
        draft = self.invoice([self.chips_line()], state=Invoice.STATE_DRAFT)
        update_draft_invoice(invoice_id=draft.pk, customer=self.customer, payment_type="credit",
                             line_items=[self.rice_line("107.50")], updated_by=self.staff)
        draft.refresh_from_db()
        self.assertEqual((draft.round_off, draft.total_amount), (D("0.50"), D("108.00")))

    # 4. Lines, taxable value and GST are identical with and without rounding
    def test_taxable_gst_and_line_totals_unchanged_by_rounding(self):
        lines = [self.chips_line(qty="3", rate="33.33"), self.rice_line("12.34")]
        rounded = self.invoice([dict(line) for line in lines])
        self.set_round_off(False)
        exact = self.invoice([dict(line) for line in lines])
        fields = ["taxable_value_snapshot", "tax_amount", "cgst_amount", "sgst_amount", "igst_amount", "line_total"]
        self.assertEqual(
            list(rounded.line_items.order_by("id").values_list(*fields)),
            list(exact.line_items.order_by("id").values_list(*fields)),
        )
        rounded.refresh_from_db()
        exact.refresh_from_db()
        self.assertNotEqual(rounded.round_off, D("0.00"))
        self.assertEqual(rounded.total_amount - rounded.round_off, exact.total_amount)

    # 5. Cash bill: the automatic payment is the rounded total, nothing left outstanding
    def test_cash_invoice_payment_uses_rounded_total(self):
        start = self.customer.outstanding_balance
        inv = self.invoice([self.chips_line()], payment_type="cash")
        payment = Payment.objects.get(invoice=inv)
        self.assertEqual(payment.amount, D("107.00"))
        inv.refresh_from_db()
        self.assertEqual(inv.payment_status, Invoice.PAYMENT_STATUS_PAID)
        self.assertEqual(Customer.objects.get(pk=self.customer.pk).outstanding_balance, start)

    def test_cash_draft_posted_later_is_paid_in_full(self):
        start = self.customer.outstanding_balance
        draft = self.invoice([self.rice_line("107.50")], payment_type="cash", state=Invoice.STATE_DRAFT)
        post_invoice(invoice_id=draft.pk, posted_by=self.staff)
        self.assertEqual(Payment.objects.get(invoice=draft).amount, D("108.00"))
        self.assertEqual(Customer.objects.get(pk=self.customer.pk).outstanding_balance, start)

    # 6. Two partial credit notes: only the completing one carries the round-off
    def test_full_reversal_in_two_notes_returns_balance_exactly(self):
        start = Customer.objects.get(pk=self.customer.pk).outstanding_balance
        inv = self.invoice([self.chips_line(qty="2", rate="51.00")])  # 102.00 + 5.10 = 107.10 -> 107.00
        inv.refresh_from_db()
        self.assertEqual((inv.round_off, inv.total_amount), (D("-0.10"), D("107.00")))
        line = inv.line_items.get()
        reversal = {"invoice_line_item": line, "product": self.chips, "quantity": D("1")}

        first = create_credit_note(original_invoice=inv, reason="part 1", created_by=self.staff, line_items=[dict(reversal)])
        self.assertEqual((first.round_off, first.total_amount), (D("0.00"), D("53.55")))
        self.assertEqual(Customer.objects.get(pk=self.customer.pk).outstanding_balance, start + D("53.45"))

        second = create_credit_note(original_invoice=inv, reason="part 2", created_by=self.staff, line_items=[dict(reversal)])
        self.assertEqual((second.round_off, second.total_amount), (D("-0.10"), D("53.45")))
        self.assertEqual(first.total_amount + second.total_amount, inv.total_amount)
        self.assertEqual(Customer.objects.get(pk=self.customer.pk).outstanding_balance, start)

    def test_single_full_credit_note_carries_round_off(self):
        inv = self.invoice([self.chips_line(), self.rice_line("10.00")])  # 107.10 + 10.00 = 117.10 -> 117.00
        lines = list(inv.line_items.order_by("id"))
        note = create_credit_note(original_invoice=inv, created_by=self.staff, line_items=[
            {"invoice_line_item": line, "product": line.product, "quantity": line.base_quantity} for line in lines
        ])
        inv.refresh_from_db()
        self.assertEqual(note.round_off, inv.round_off)
        self.assertEqual(note.total_amount, inv.total_amount)

    def test_partial_note_on_one_line_of_two_has_no_round_off(self):
        inv = self.invoice([self.chips_line(), self.rice_line("10.00")])
        first_line = inv.line_items.order_by("id").first()
        note = create_credit_note(original_invoice=inv, created_by=self.staff, line_items=[
            {"invoice_line_item": first_line, "product": first_line.product, "quantity": first_line.base_quantity}
        ])
        self.assertEqual(note.round_off, D("0.00"))
        self.assertEqual(note.total_amount, D("107.10"))

    # 7. Amendment: the replacement invoice gets its own round-off
    def test_amendment_replacement_gets_its_own_round_off(self):
        original = self.invoice([self.chips_line()])  # 107.10 -> 107.00 (-0.10)
        _, replacement = amend_invoice(
            invoice_id=original.pk, corrected_line_items=[self.rice_line("53.55")], customer=self.customer,
            payment_type="credit", amended_by=self.admin, reason="wrong item",
        )
        original.refresh_from_db()
        self.assertEqual((original.state, original.round_off, original.total_amount), (Invoice.STATE_CANCELLED, D("-0.10"), D("107.00")))
        self.assertEqual((replacement.round_off, replacement.total_amount), (D("0.45"), D("54.00")))

    def test_cancelled_invoice_drops_out_of_the_balance(self):
        start = Customer.objects.get(pk=self.customer.pk).outstanding_balance
        inv = self.invoice([self.chips_line()])
        from billing.services import cancel_invoice

        cancel_invoice(invoice_id=inv.pk, cancelled_by=self.admin, reason="test")
        self.assertEqual(Customer.objects.get(pk=self.customer.pk).outstanding_balance, start)

    # 8. Posted round_off is immutable: model guard and database trigger
    def test_posted_round_off_cannot_change(self):
        inv = self.invoice([self.chips_line()])
        inv.refresh_from_db()
        inv.round_off = D("0.00")
        with self.assertRaises(ValueError):
            inv.save()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice.objects.filter(pk=inv.pk).update(round_off=D("0.00"))
        self.assertEqual(Invoice.objects.get(pk=inv.pk).round_off, D("-0.10"))

    def test_credit_note_round_off_cannot_change(self):
        inv = self.invoice([self.chips_line()])
        line = inv.line_items.get()
        note = create_credit_note(original_invoice=inv, created_by=self.staff, line_items=[
            {"invoice_line_item": line, "product": self.chips, "quantity": D("1")}
        ])
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                CreditNote.objects.filter(pk=note.pk).update(round_off=D("0.00"))

    # 10. Sales GST report: R.OFF column and reconciliation
    def test_sales_gst_report_round_off_column_reconciles(self):
        today = timezone.localdate()
        a = self.invoice([self.chips_line()])                    # 107.10 -> 107.00 (-0.10)
        b = self.invoice([self.rice_line("107.50")])             # 107.50 -> 108.00 (+0.50)
        self.set_round_off(False)
        c = self.invoice([self.chips_line()])                    # exact 107.10 (0.00)
        data = get_sales_gst_report_data(today, today)
        rows = {row["bill_no"]: row for row in data["rows"]}
        for inv, bill_amt, r_off in [(a, "107.00", "-0.10"), (b, "108.00", "0.50"), (c, "107.10", "0.00")]:
            inv.refresh_from_db()
            row = rows[inv.invoice_number]
            self.assertEqual((row["bill_amt"], row["r_off"]), (bill_amt, r_off))
            self.assertEqual(D(row["bill_amt"]), D(row["taxable"]) + D(row["tax"]) + D(row["r_off"]))
        totals = data["totals"]
        self.assertEqual(D(totals["bill_amt"]), D(totals["taxable"]) + D(totals["tax"]) + D(totals["r_off"]))
        self.assertEqual(totals["r_off"], "0.40")
        self.assertEqual(totals["bill_amt"], "322.10")

    def test_sales_summary_net_sales_includes_round_off(self):
        a = self.invoice([self.chips_line()])
        b = self.invoice([self.rice_line("107.50")])
        client = APIClient()
        client.force_authenticate(self.staff)
        today = timezone.localdate().isoformat()
        response = client.get("/api/reports/sales/", {"from": today, "to": today})
        self.assertEqual(response.status_code, 200)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(response.data["round_off"], D("0.40"))
        self.assertEqual(response.data["net_sales"], a.total_amount + b.total_amount)
        self.assertEqual(response.data["taxable_sales"], D("209.50"))  # exact, no round-off

    # 11. PDF: ROUND OFF row and rounded total in words when non-zero; no row when zero
    def pdf_text(self, invoice):
        invoice.refresh_from_db()
        return pymupdf.open("pdf", build_invoice_a5_pdf(invoice))[0].get_text()

    def test_pdf_shows_round_off_and_rounded_total(self):
        text = self.pdf_text(self.invoice([self.chips_line()]))
        self.assertIn("ROUND OFF", text)
        self.assertIn("-0.10", text)
        self.assertIn("Rs. 107.00", text)
        self.assertIn(amount_to_words(D("107.00")), text)
        self.assertNotIn("Rs. 107.10", text)

    def test_pdf_positive_round_off_sign(self):
        text = self.pdf_text(self.invoice([self.rice_line("107.50")]))
        self.assertIn("ROUND OFF", text)
        self.assertIn("+0.50", text)
        self.assertIn("Rs. 108.00", text)

    def test_pdf_has_no_round_off_row_when_zero(self):
        text = self.pdf_text(self.invoice([self.rice_line("108.00")]))
        self.assertNotIn("ROUND OFF", text)
        self.assertIn("Rs. 108.00", text)
        self.set_round_off(False)
        text = self.pdf_text(self.invoice([self.chips_line()]))
        self.assertNotIn("ROUND OFF", text)
        self.assertIn("Rs. 107.10", text)


class BillingSettingsEndpointTests(APITestCase):
    # 12. Staff can read only the round-off switch
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="bs-staff", password="Pass-12345!", role="staff")
        cls.admin = User.objects.create_user(username="bs-admin", password="Pass-12345!", role="admin")

    def get(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client.get("/api/billing-settings/")

    def test_staff_reads_only_the_round_off_switch(self):
        BusinessProfile.objects.create(business_name="X", gstin="G", registered_address="A", state="S", state_code="27")
        response = self.get(self.staff)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"round_off_invoice_total": True})

    def test_reflects_the_profile_setting(self):
        BusinessProfile.objects.create(business_name="X", gstin="G", registered_address="A", state="S", state_code="27",
                                       round_off_invoice_total=False)
        self.assertEqual(self.get(self.staff).json(), {"round_off_invoice_total": False})

    def test_no_profile_means_no_round_off(self):
        self.assertEqual(self.get(self.staff).json(), {"round_off_invoice_total": False})

    def test_requires_login(self):
        self.assertIn(self.get().status_code, (401, 403))

    def test_staff_cannot_read_the_profile_but_admin_can_toggle_it(self):
        BusinessProfile.objects.create(business_name="X", gstin="G", registered_address="A", state="S", state_code="27")
        staff = APIClient()
        staff.force_authenticate(self.staff)
        self.assertEqual(staff.get("/api/business-profile/").status_code, 403)
        admin = APIClient()
        admin.force_authenticate(self.admin)
        response = admin.patch("/api/business-profile/", {"round_off_invoice_total": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["round_off_invoice_total"])
        self.assertEqual(self.get(self.staff).json(), {"round_off_invoice_total": False})


class RoundOffMigrationTests(TransactionTestCase):
    """9. Migration 0020 leaves existing invoices untouched and reverses cleanly."""

    before = [("billing", "0019_creditnote_number_required_invoice_date_immutable"),
              ("inventory", "0016_allow_draft_purchase_idempotency_key_delete")]
    after = [("billing", "0020_invoice_round_off")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def trigger_body(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT prosrc FROM pg_proc WHERE proname = 'stockbill_protect_history'")
            return cursor.fetchone()[0]

    def test_existing_invoices_untouched_and_migration_reverses(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        Invoice19 = old_apps.get_model("billing", "Invoice")  # noqa: N806
        Profile19 = old_apps.get_model("billing", "BusinessProfile")  # noqa: N806
        Profile19.objects.create(business_name="Shop", gstin="G", registered_address="A", state="S", state_code="27")
        posted = Invoice19.objects.create(invoice_number="INV-20261121124548", state="POSTED", total_amount=D("107.10"),
                                          invoice_date=datetime.date(2026, 11, 21))
        cancelled = Invoice19.objects.create(invoice_number="INV-20261120000000", state="CANCELLED", total_amount=D("55.55"))
        self.assertNotIn("round_off", self.trigger_body())

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new_apps = executor.loader.project_state(self.after).apps
        Invoice20 = new_apps.get_model("billing", "Invoice")  # noqa: N806
        Profile20 = new_apps.get_model("billing", "BusinessProfile")  # noqa: N806
        self.assertEqual(Invoice20.objects.get(pk=posted.pk).total_amount, D("107.10"))
        self.assertEqual(Invoice20.objects.get(pk=posted.pk).round_off, D("0.00"))
        self.assertEqual(Invoice20.objects.get(pk=cancelled.pk).total_amount, D("55.55"))
        self.assertEqual(Invoice20.objects.get(pk=cancelled.pk).round_off, D("0.00"))
        self.assertTrue(Profile20.objects.get().round_off_invoice_total)
        body = self.trigger_body()
        self.assertIn("OLD.round_off IS DISTINCT FROM NEW.round_off", body)
        self.assertIn("inventory_purchaseidempotencykey", body)  # inventory/0016 rule kept
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice20.objects.filter(pk=posted.pk).update(round_off=D("0.50"))

        # Backwards restores the inventory/0016 function body exactly.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.before)
        from importlib import import_module

        previous = import_module("inventory.migrations.0016_allow_draft_purchase_idempotency_key_delete").TRIGGER_FUNCTION
        self.assertNotIn("round_off", self.trigger_body())
        # The Python source escapes % as %% for the DB driver; PostgreSQL stores %.
        self.assertIn(self.trigger_body().strip(), previous.replace("%%", "%"))
