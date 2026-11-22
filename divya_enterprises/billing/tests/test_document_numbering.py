"""GST document numbering (CGST Rules 46(b) and 53): DE/<fy>/<serial>, CN/<fy>/<serial>."""

import io
import re
import threading
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient

from billing.models import (
    AuditLog,
    BusinessProfile,
    CreditNote,
    CreditNoteNumberCounter,
    Invoice,
    InvoiceNumberCounter,
)
from billing.numbering import DocumentNumberError, next_invoice_number
from billing.pdf import render_invoice_html
from billing.pdf_engine import build_invoice_a5_pdf
from billing.services import amend_invoice, create_credit_note, create_invoice, post_invoice
from customers.models import Customer
from inventory.models import Product, TaxRate
from inventory.purchase_numbering import financial_year_code

GST_NUMBER = re.compile(r"^[A-Za-z0-9/-]{1,16}$")


def _fy():
    return financial_year_code(timezone.localdate())


class NumberingFixtures:
    def make_fixtures(self):
        BusinessProfile.objects.get_or_create(
            defaults=dict(
                business_name="Divya Enterprises", gstin="27ABCDE1234F1Z5",
                registered_address="Mumbai", state="Maharashtra", state_code="27",
            )
        )
        self.user = get_user_model().objects.create_user(
            username=f"num_admin_{self.id()[-20:]}", email="n@t.local", password="P123!", role="admin"
        )
        self.tax = TaxRate.objects.create(name=f"18-{self.id()[-20:]}", rate=Decimal("18.00"))
        self.customer = Customer.objects.create(
            name="Numbering Traders", contact_info="9000000001", customer_type="B2B", state_code="27",
        )

    def product(self, name, stock=100):
        return Product.objects.create(
            name=name, unit_type="piece", unit_conversion_factor=1,
            default_price=100, cost_price=60, tax=self.tax, current_stock=stock,
        )

    def lines(self, product, qty=2):
        return [{
            "product": product, "quantity": Decimal(str(qty)), "rate_charged": Decimal("100"),
            "tax_rate": Decimal("18"), "discount_amount": Decimal("0"),
            "sales_unit_name": "piece", "conversion_factor": Decimal("1"),
        }]

    def draft(self, product, qty=2, customer=None, payment_type="cash"):
        return create_invoice(
            customer=customer, created_by=self.user, payment_type=payment_type,
            line_items=self.lines(product, qty), state=Invoice.STATE_DRAFT, place_of_supply="27",
        )

    def direct_post(self, product, qty=2):
        return create_invoice(
            customer=None, created_by=self.user, payment_type="cash",
            line_items=self.lines(product, qty), state=Invoice.STATE_POSTED, place_of_supply="27",
        )


class InvoiceNumberingTests(NumberingFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    # 1. Drafts are unnumbered; posting assigns consecutive numbers.
    def test_posting_assigns_consecutive_numbers_and_drafts_have_none(self):
        d1 = self.draft(self.product("P1"))
        d2 = self.draft(self.product("P2"))
        self.assertIsNone(d1.invoice_number)
        self.assertIsNone(d2.invoice_number)
        p1 = post_invoice(invoice_id=d1.pk, posted_by=self.user)
        p2 = post_invoice(invoice_id=d2.pk, posted_by=self.user)
        self.assertEqual(p1.invoice_number, f"DE/{_fy()}/00001")
        self.assertEqual(p2.invoice_number, f"DE/{_fy()}/00002")
        self.assertEqual(Invoice.objects.get(pk=d1.pk).invoice_number, f"DE/{_fy()}/00001")

    def test_deleted_draft_leaves_no_gap(self):
        doomed = self.draft(self.product("Doomed"))
        doomed.delete()
        posted = post_invoice(invoice_id=self.draft(self.product("Kept")).pk, posted_by=self.user)
        self.assertEqual(posted.invoice_number, f"DE/{_fy()}/00001")

    def test_reposting_a_posted_invoice_does_not_consume_a_number(self):
        d = self.draft(self.product("Twice"))
        post_invoice(invoice_id=d.pk, posted_by=self.user)
        again = post_invoice(invoice_id=d.pk, posted_by=self.user)
        self.assertEqual(again.invoice_number, f"DE/{_fy()}/00001")
        self.assertEqual(InvoiceNumberCounter.objects.get(fy_code=_fy()).last_serial, 1)

    # 2. Direct post and the amendment replacement share the same series.
    def test_direct_post_and_amend_replacement_share_series(self):
        product = self.product("Shared", stock=50)
        first = self.direct_post(product)
        second = post_invoice(invoice_id=self.draft(product).pk, posted_by=self.user)
        # Cash invoices carry a payment and are not amendable; amend a credit one.
        credit = create_invoice(
            customer=self.customer, created_by=self.user, payment_type="credit",
            line_items=self.lines(product), state=Invoice.STATE_POSTED, place_of_supply="27",
        )
        original, replacement = amend_invoice(
            invoice_id=credit.pk, corrected_line_items=self.lines(product, 3), customer=self.customer,
            payment_type="credit", notes="", place_of_supply="27", amended_by=self.user, reason="qty fix",
        )
        fy = _fy()
        self.assertEqual(
            [first.invoice_number, second.invoice_number, credit.invoice_number, replacement.invoice_number],
            [f"DE/{fy}/00001", f"DE/{fy}/00002", f"DE/{fy}/00003", f"DE/{fy}/00004"],
        )
        self.assertEqual(original.invoice_number, f"DE/{fy}/00003")
        self.assertEqual(original.state, Invoice.STATE_CANCELLED)

    # 3. Failed posts consume no serial.
    def test_insufficient_stock_post_consumes_no_number(self):
        short = self.draft(self.product("Short", stock=1), qty=5)
        with self.assertRaises(serializers.ValidationError):
            post_invoice(invoice_id=short.pk, posted_by=self.user)
        self.assertIsNone(Invoice.objects.get(pk=short.pk).invoice_number)
        ok = post_invoice(invoice_id=self.draft(self.product("Ok")).pk, posted_by=self.user)
        self.assertEqual(ok.invoice_number, f"DE/{_fy()}/00001")

    def test_credit_limit_failure_consumes_no_number(self):
        over = self.draft(self.product("Over"), customer=self.customer, payment_type="credit")
        self.customer.credit_limit = Decimal("10.00")
        self.customer.save()
        with self.assertRaises(serializers.ValidationError):
            post_invoice(invoice_id=over.pk, posted_by=self.user)
        with self.assertRaises(serializers.ValidationError):
            create_invoice(
                customer=self.customer, created_by=self.user, payment_type="credit",
                line_items=self.lines(self.product("Over2")), state=Invoice.STATE_POSTED, place_of_supply="27",
            )
        ok = self.direct_post(self.product("AfterFail"))
        self.assertEqual(ok.invoice_number, f"DE/{_fy()}/00001")

    # 5. Financial-year boundary.
    def test_fy_boundary_restarts_series(self):
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 3, 31)):
            march_a = self.direct_post(self.product("Mar1"))
            march_b = self.direct_post(self.product("Mar2"))
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 4, 1)):
            april = self.direct_post(self.product("Apr1"))
        self.assertEqual(march_a.invoice_number, "DE/25-26/00001")
        self.assertEqual(march_b.invoice_number, "DE/25-26/00002")
        self.assertEqual(april.invoice_number, "DE/26-27/00001")
        self.assertEqual(march_a.invoice_date, date(2026, 3, 31))
        self.assertEqual(april.invoice_date, date(2026, 4, 1))

    # 6. IST, not UTC: 2026-04-01 01:00 IST is still 31 March in UTC.
    def test_ist_date_decides_financial_year(self):
        utc_instant = datetime(2026, 3, 31, 19, 30, tzinfo=dt_timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=utc_instant):
            draft = self.draft(self.product("Midnight"))
            posted = post_invoice(invoice_id=draft.pk, posted_by=self.user)
        self.assertEqual(posted.invoice_number, "DE/26-27/00001")
        self.assertEqual(posted.invoice_date, date(2026, 4, 1))

    # D4: invoice_date is the posting date, not the draft date.
    def test_invoice_date_is_posting_date(self):
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 11, 1, 6, 0, tzinfo=dt_timezone.utc)):
            draft = self.draft(self.product("Dated"))
        self.assertEqual(draft.invoice_date, date(2026, 11, 1))
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 11, 15, 6, 0, tzinfo=dt_timezone.utc)):
            posted = post_invoice(invoice_id=draft.pk, posted_by=self.user)
        self.assertEqual(posted.invoice_date, date(2026, 11, 15))
        self.assertEqual(Invoice.objects.get(pk=draft.pk).invoice_date, date(2026, 11, 15))

    # 7. Format guarantees.
    def test_generated_numbers_are_gst_compliant(self):
        for i in range(3):
            number = self.direct_post(self.product(f"Fmt{i}")).invoice_number
            self.assertRegex(number, GST_NUMBER)
            self.assertLessEqual(len(number), 16)

    @override_settings(INVOICE_NUMBER_PREFIX="DIVYAENT")
    def test_too_long_prefix_raises_and_issues_nothing(self):
        draft = self.draft(self.product("Long"))
        with self.assertRaises(DocumentNumberError):
            post_invoice(invoice_id=draft.pk, posted_by=self.user)
        self.assertEqual(Invoice.objects.get(pk=draft.pk).state, Invoice.STATE_DRAFT)
        self.assertFalse(InvoiceNumberCounter.objects.filter(last_serial__gt=0).exists())

    @override_settings(INVOICE_NUMBER_PREFIX="DE INV")
    def test_prefix_with_illegal_character_raises(self):
        with self.assertRaises(DocumentNumberError):
            with transaction.atomic():
                next_invoice_number(date(2026, 11, 15))

    def test_number_requires_atomic_block(self):
        # TestCase wraps tests in a transaction, so simulate a caller outside one.
        with mock.patch.object(connections["default"], "in_atomic_block", False):
            with self.assertRaises(DocumentNumberError):
                next_invoice_number(date(2026, 11, 15))

    # 11. invoice_date immutability: model guard and database trigger.
    def test_posted_invoice_date_is_immutable(self):
        posted = self.direct_post(self.product("Locked"))
        posted.invoice_date = date(2020, 1, 1)
        with self.assertRaises(ValueError):
            posted.save()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice.objects.filter(pk=posted.pk).update(invoice_date=date(2020, 1, 1))
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice.objects.filter(pk=posted.pk).update(invoice_number="DE/26-27/99999")
        self.assertEqual(Invoice.objects.get(pk=posted.pk).invoice_date, timezone.localdate())

    def test_draft_date_remains_editable(self):
        draft = self.draft(self.product("Editable"))
        Invoice.objects.filter(pk=draft.pk).update(invoice_date=date(2026, 10, 1))
        self.assertEqual(Invoice.objects.get(pk=draft.pk).invoice_date, date(2026, 10, 1))

    def test_check_constraint_rejects_unnumbered_posted_invoice(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice.objects.create(state=Invoice.STATE_POSTED, invoice_number=None, total_amount=Decimal("1"))

    def test_counter_rows_cannot_be_deleted(self):
        self.direct_post(self.product("Ctr"))
        counter = InvoiceNumberCounter.objects.get(fy_code=_fy())
        with self.assertRaises(ValueError):
            counter.delete()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                InvoiceNumberCounter.objects.filter(pk=counter.pk).delete()

    # 12. Draft PDFs show DRAFT, never "None".
    def test_draft_pdf_and_html_render_draft(self):
        import pymupdf

        draft = self.draft(self.product("PdfDraft"))
        pdf_bytes = build_invoice_a5_pdf(draft, copy_type="original")
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        self.assertIn("DRAFT", text)
        self.assertNotIn("None", text)
        html = render_invoice_html(draft)
        self.assertIn("Invoice: DRAFT", html)
        self.assertNotIn("Invoice: None", html)


class CreditNoteNumberingTests(NumberingFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _credit_note(self, invoice, qty=1):
        line = invoice.line_items.first()
        return create_credit_note(
            original_invoice=invoice, reason="return", created_by=self.user,
            line_items=[{"invoice_line_item": line, "product": line.product, "quantity": Decimal(str(qty))}],
        )

    # 10. Consecutive CN numbers.
    def test_credit_notes_are_numbered_consecutively(self):
        invoice = create_invoice(
            customer=self.customer, created_by=self.user, payment_type="credit",
            line_items=self.lines(self.product("CNP", stock=50), 5), state=Invoice.STATE_POSTED, place_of_supply="27",
        )
        first = self._credit_note(invoice)
        second = self._credit_note(invoice)
        self.assertEqual(first.credit_note_number, f"CN/{_fy()}/00001")
        self.assertEqual(second.credit_note_number, f"CN/{_fy()}/00002")
        self.assertRegex(second.credit_note_number, GST_NUMBER)
        # Invoice and credit-note series are independent.
        self.assertEqual(invoice.invoice_number, f"DE/{_fy()}/00001")

    def test_failed_credit_note_consumes_no_number(self):
        invoice = create_invoice(
            customer=self.customer, created_by=self.user, payment_type="credit",
            line_items=self.lines(self.product("CNF", stock=50), 2), state=Invoice.STATE_POSTED, place_of_supply="27",
        )
        with self.assertRaises(serializers.ValidationError):
            self._credit_note(invoice, qty=99)
        self.assertEqual(self._credit_note(invoice).credit_note_number, f"CN/{_fy()}/00001")


class NumberingApiTests(NumberingFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _body(self, product, **extra):
        body = {
            "customer": self.customer.pk, "payment_type": "credit", "place_of_supply": "27", "tax_mode": "exclusive",
            "line_items": [{"product": product.pk, "quantity": "2", "rate_charged": "100.00", "tax_rate": "18.00"}],
        }
        body.update(extra)
        return body

    # 8. Client-supplied invoice numbers are ignored.
    def test_api_ignores_client_invoice_number(self):
        product = self.product("ApiP")
        draft = self.client.post("/api/invoices/drafts/", self._body(product, invoice_number="INV-20261115165912"), format="json")
        self.assertEqual(draft.status_code, 201, draft.data)
        self.assertIsNone(draft.data["invoice_number"])
        posted = self.client.post(f"/api/invoices/{draft.data['id']}/post/", format="json")
        self.assertEqual(posted.status_code, 200, posted.data)
        self.assertEqual(posted.data["invoice_number"], f"DE/{_fy()}/00001")
        direct = self.client.post("/api/invoices/", self._body(self.product("ApiQ"), invoice_number="HACK-1"), format="json")
        self.assertEqual(direct.status_code, 201, direct.data)
        self.assertEqual(direct.data["invoice_number"], f"DE/{_fy()}/00002")

    def test_amend_without_invoice_number(self):
        product = self.product("AmendP", stock=50)
        original = self.client.post("/api/invoices/", self._body(product), format="json")
        self.assertEqual(original.status_code, 201, original.data)
        body = self._body(product, reason="wrong qty")
        response = self.client.post(f"/api/invoices/{original.data['id']}/amend/", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["replacement"]["invoice_number"], f"DE/{_fy()}/00002")
        self.assertEqual(response.data["original"]["invoice_number"], f"DE/{_fy()}/00001")

    def test_idempotent_retry_with_same_body_returns_same_invoice(self):
        body = self._body(self.product("Idem"))
        first = self.client.post("/api/invoices/", body, format="json", HTTP_IDEMPOTENCY_KEY="retry-1")
        retry = self.client.post("/api/invoices/", body, format="json", HTTP_IDEMPOTENCY_KEY="retry-1")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["id"], first.data["id"])
        self.assertEqual(Invoice.objects.filter(state=Invoice.STATE_POSTED).count(), 1)
        self.assertEqual(InvoiceNumberCounter.objects.get(fy_code=_fy()).last_serial, 1)

    def test_credit_note_api_exposes_number(self):
        product = self.product("CnApi", stock=50)
        invoice = self.client.post("/api/invoices/", self._body(product), format="json").data
        line = invoice["line_items"][0]
        response = self.client.post("/api/credit-notes/", {
            "original_invoice": invoice["id"], "reason": "return", "credit_note_number": "CN/99-00/99999",
            "line_items": [{"invoice_line_item": line["id"], "product": product.pk, "quantity": "1"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["credit_note_number"], f"CN/{_fy()}/00001")

    def test_draft_pdf_filename_has_no_none(self):
        draft = self.client.post("/api/invoices/drafts/", self._body(self.product("PdfName")), format="json").data
        response = self.client.get(f"/api/invoices/{draft['id']}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"invoice-draft-{draft['id']}-original.pdf", response["Content-Disposition"])


class SetDocumentCounterCommandTests(NumberingFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_sets_counter_and_audits(self):
        call_command("set_document_counter", "--doc", "invoice", "--fy", _fy(), "--last-serial", "412", stdout=io.StringIO())
        self.assertEqual(self.direct_post(self.product("After412")).invoice_number, f"DE/{_fy()}/00413")
        log = AuditLog.objects.get(action="document_counter_set")
        self.assertEqual(log.metadata, {"doc": "invoice", "fy": _fy(), "old_last_serial": 0, "new_last_serial": 412})

    def test_refuses_to_go_below_issued_serial(self):
        self.direct_post(self.product("I1"))
        self.direct_post(self.product("I2"))
        with self.assertRaises(CommandError):
            call_command("set_document_counter", "--doc", "invoice", "--fy", _fy(), "--last-serial", "1")
        self.assertEqual(InvoiceNumberCounter.objects.get(fy_code=_fy()).last_serial, 2)
        self.assertFalse(AuditLog.objects.filter(action="document_counter_set").exists())

    def test_credit_note_counter_and_bad_fy(self):
        call_command("set_document_counter", "--doc", "credit_note", "--fy", "26-27", "--last-serial", "7", stdout=io.StringIO())
        self.assertEqual(CreditNoteNumberCounter.objects.get(fy_code="26-27").last_serial, 7)
        with self.assertRaises(CommandError):
            call_command("set_document_counter", "--doc", "invoice", "--fy", "2026", "--last-serial", "1")


class ConcurrentPostingTests(NumberingFixtures, TransactionTestCase):
    """4. Parallel posts on separate connections get distinct consecutive numbers."""

    def setUp(self):
        self.make_fixtures()

    def test_parallel_posts_get_distinct_consecutive_numbers(self):
        drafts = [self.draft(self.product(f"Par{i}")) for i in range(2)]
        barrier = threading.Barrier(len(drafts))
        results, errors = {}, []

        def worker(invoice_id):
            try:
                barrier.wait(timeout=10)
                results[invoice_id] = post_invoice(invoice_id=invoice_id, posted_by=self.user).invoice_number
            except Exception as exc:  # surfaced via the assertion below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(d.pk,)) for d in drafts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        fy = _fy()
        self.assertEqual(sorted(results.values()), [f"DE/{fy}/00001", f"DE/{fy}/00002"])


class NumberingMigrationTests(TransactionTestCase):
    """9 & 10. Legacy numbers survive; existing credit notes are backfilled in order."""

    before = [("billing", "0014_add_amendment_links")]
    after = [("billing", "0019_creditnote_number_required_invoice_date_immutable")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_legacy_numbers_kept_drafts_cleared_credit_notes_backfilled(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        Invoice0014 = old_apps.get_model("billing", "Invoice")
        CreditNote0014 = old_apps.get_model("billing", "CreditNote")

        legacy = Invoice0014.objects.create(invoice_number="INV-20261115165912", state="POSTED", total_amount=Decimal("10"))
        cancelled = Invoice0014.objects.create(invoice_number="INV-20261015090000", state="CANCELLED", total_amount=Decimal("5"))
        draft = Invoice0014.objects.create(invoice_number="INV-20261116000000", state="DRAFT", total_amount=Decimal("1"))
        legacy_date = Invoice0014.objects.get(pk=legacy.pk).invoice_date

        # Three notes: two in FY 26-27 created out of id order, one in FY 25-26.
        notes = [CreditNote0014.objects.create(original_invoice_id=legacy.pk, total_amount=Decimal("1")) for _ in range(3)]
        stamps = {
            notes[0].pk: ("2026-11-02 10:00+05:30", "2026-11-02"),
            notes[1].pk: ("2026-11-01 10:00+05:30", "2026-11-01"),
            notes[2].pk: ("2026-03-20 10:00+05:30", "2026-03-20"),
        }
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE billing_creditnote DISABLE TRIGGER stockbill_protect_billing_creditnote")
            for pk, (created, note_date) in stamps.items():
                cursor.execute("UPDATE billing_creditnote SET created_at=%s, note_date=%s WHERE id=%s", [created, note_date, pk])
            cursor.execute("ALTER TABLE billing_creditnote ENABLE TRIGGER stockbill_protect_billing_creditnote")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        # Read through the models as of self.after: later migrations add
        # columns (e.g. billing 0020 round_off) the current models expect.
        after_apps = executor.loader.project_state(self.after).apps
        Invoice = after_apps.get_model("billing", "Invoice")  # noqa: N806
        CreditNote = after_apps.get_model("billing", "CreditNote")  # noqa: N806
        CreditNoteNumberCounter = after_apps.get_model("billing", "CreditNoteNumberCounter")  # noqa: N806

        self.assertEqual(Invoice.objects.get(pk=legacy.pk).invoice_number, "INV-20261115165912")
        self.assertEqual(Invoice.objects.get(pk=legacy.pk).invoice_date, legacy_date)
        self.assertEqual(Invoice.objects.get(pk=cancelled.pk).invoice_number, "INV-20261015090000")
        self.assertIsNone(Invoice.objects.get(pk=draft.pk).invoice_number)

        numbers = dict(CreditNote.objects.values_list("pk", "credit_note_number"))
        self.assertEqual(numbers[notes[1].pk], "CN/26-27/00001")  # earliest created_at in FY 26-27
        self.assertEqual(numbers[notes[0].pk], "CN/26-27/00002")
        self.assertEqual(numbers[notes[2].pk], "CN/25-26/00001")
        self.assertEqual(CreditNoteNumberCounter.objects.get(fy_code="26-27").last_serial, 2)
        self.assertEqual(CreditNoteNumberCounter.objects.get(fy_code="25-26").last_serial, 1)

        # The append-only trigger is back on after the backfill.
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                CreditNote.objects.filter(pk=notes[0].pk).update(reason="tamper")

    # Specific to the billing_invoice branch (purchases also guard invoice_date).
    INVOICE_DATE_GUARD = "NEW.invoice_number\n               OR OLD.invoice_date IS DISTINCT FROM NEW.invoice_date"

    def _trigger_body(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT prosrc FROM pg_proc WHERE proname = 'stockbill_protect_history'")
            return cursor.fetchone()[0]

    def test_backwards_round_trip(self):
        self.assertIn(self.INVOICE_DATE_GUARD, self._trigger_body())
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        body = self._trigger_body()
        self.assertNotIn(self.INVOICE_DATE_GUARD, body)
        self.assertNotIn("billing_invoicenumbercounter", body)
        # Earlier protections (purchases, opening stock) are still in place.
        self.assertIn("inventory_openingstocknumbercounter", body)
        self.assertIn("Posted and cancelled purchase financial data is immutable", body)
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        self.assertIn(self.INVOICE_DATE_GUARD, self._trigger_body())
