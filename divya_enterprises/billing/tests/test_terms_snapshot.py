"""Release B4: terms and seller details are fixed on the invoice at posting."""

import datetime
from decimal import Decimal as D

import pymupdf
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from billing.models import BusinessProfile, Invoice
from billing.pdf_engine import build_invoice_a5_pdf
from billing.services import amend_invoice, create_invoice, post_invoice
from billing.tests.test_shop_details import SHOP, ShopFixture

OLD_TERMS = "1. Interest at 18% p.a. after 30 days."
NEW_TERMS = "1. Interest at 24% p.a. after 15 days."


class TermsSnapshotTests(ShopFixture, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_stock()
        cls.profile = BusinessProfile.objects.create(**SHOP, terms_and_conditions=OLD_TERMS)

    def set_profile(self, **fields):
        BusinessProfile.objects.filter(pk=self.profile.pk).update(**fields)

    def pdf_text(self, invoice):
        invoice.refresh_from_db()
        return " ".join(pymupdf.open("pdf", build_invoice_a5_pdf(invoice))[0].get_text().split())

    def post_direct(self):
        return create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit", line_items=self.line())

    def draft(self):
        return create_invoice(customer=self.customer, created_by=self.admin, payment_type="credit",
                              line_items=self.line(), state=Invoice.STATE_DRAFT)

    def test_profile_change_after_posting_does_not_change_the_invoice(self):
        invoice = self.post_direct()
        invoice.refresh_from_db()
        self.assertEqual(invoice.terms_snapshot, OLD_TERMS)
        self.set_profile(terms_and_conditions=NEW_TERMS, business_name="Renamed Store")
        text = self.pdf_text(invoice)
        self.assertIn(OLD_TERMS, text)
        self.assertNotIn(NEW_TERMS, text)
        self.assertIn("SHARMA GENERAL STORE", text)

    def test_draft_posted_after_a_profile_change_gets_the_new_details(self):
        draft = self.draft()
        draft.refresh_from_db()
        self.assertEqual(draft.terms_snapshot, "")  # drafts carry no terms
        self.assertEqual(draft.seller_business_name_snapshot, "Sharma General Store")
        self.set_profile(terms_and_conditions=NEW_TERMS, business_name="Sharma Wholesale",
                         registered_address="99 New Road, Mysuru", gstin="29ZZZZZ9999Z1Z9")
        posted = post_invoice(invoice_id=draft.pk, posted_by=self.admin)
        posted.refresh_from_db()
        self.assertEqual(posted.terms_snapshot, NEW_TERMS)
        self.assertEqual(posted.seller_business_name_snapshot, "Sharma Wholesale")
        self.assertEqual(posted.seller_address_snapshot, "99 New Road, Mysuru")
        self.assertEqual(posted.seller_gstin_snapshot, "29ZZZZZ9999Z1Z9")
        self.assertIn(NEW_TERMS, self.pdf_text(posted))

    def test_draft_pdf_prints_the_current_profile_terms(self):
        draft = self.draft()
        self.set_profile(terms_and_conditions=NEW_TERMS)
        self.assertIn(NEW_TERMS, self.pdf_text(draft))

    def test_amendment_replacement_gets_the_terms_in_force(self):
        original = self.post_direct()
        self.set_profile(terms_and_conditions=NEW_TERMS)
        original_after, replacement = amend_invoice(
            invoice_id=original.pk, corrected_line_items=self.line(), customer=self.customer,
            payment_type="credit", amended_by=self.admin, reason="qty",
        )
        self.assertEqual(original_after.terms_snapshot, OLD_TERMS)
        self.assertEqual(replacement.terms_snapshot, NEW_TERMS)

    def test_terms_snapshot_is_immutable_after_posting(self):
        invoice = self.post_direct()
        invoice.refresh_from_db()
        invoice.terms_snapshot = "tampered"
        with self.assertRaises(ValueError):
            invoice.save()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice.objects.filter(pk=invoice.pk).update(terms_snapshot="tampered")
        self.assertEqual(Invoice.objects.get(pk=invoice.pk).terms_snapshot, OLD_TERMS)


class TermsBackfillMigrationTests(TransactionTestCase):
    before = [("billing", "0024_businessprofile_terms_default_empty")]
    after = [("billing", "0025_invoice_terms_snapshot")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def trigger_body(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT prosrc FROM pg_proc WHERE proname = 'stockbill_protect_history'")
            return cursor.fetchone()[0]

    def test_backfill_fills_issued_invoices_and_migration_reverses(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        old.get_model("billing", "BusinessProfile").objects.create(**SHOP, terms_and_conditions=OLD_TERMS)
        Invoice22 = old.get_model("billing", "Invoice")  # noqa: N806
        posted = Invoice22.objects.create(invoice_number="INV-20261121124548", state="POSTED", total_amount=D("10"),
                                          invoice_date=datetime.date(2026, 11, 21))
        cancelled = Invoice22.objects.create(invoice_number="INV-20261120000000", state="CANCELLED", total_amount=D("5"))
        draft = Invoice22.objects.create(state="DRAFT", total_amount=D("1"))
        self.assertNotIn("terms_snapshot", self.trigger_body())

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        Invoice23 = executor.loader.project_state(self.after).apps.get_model("billing", "Invoice")  # noqa: N806
        self.assertEqual(Invoice23.objects.get(pk=posted.pk).terms_snapshot, OLD_TERMS)
        self.assertEqual(Invoice23.objects.get(pk=cancelled.pk).terms_snapshot, OLD_TERMS)
        self.assertEqual(Invoice23.objects.get(pk=draft.pk).terms_snapshot, "")
        self.assertEqual(Invoice23.objects.get(pk=posted.pk).total_amount, D("10"))  # nothing else touched
        body = self.trigger_body()
        self.assertIn("OLD.terms_snapshot IS DISTINCT FROM NEW.terms_snapshot", body)
        self.assertIn("OLD.round_off IS DISTINCT FROM NEW.round_off", body)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Invoice23.objects.filter(pk=posted.pk).update(terms_snapshot="x")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.before)
        from importlib import import_module

        previous = import_module("billing.migrations.0020_invoice_round_off").TRIGGER_FUNCTION
        self.assertNotIn("terms_snapshot", self.trigger_body())
        self.assertIn(self.trigger_body().strip(), previous.replace("%%", "%"))
