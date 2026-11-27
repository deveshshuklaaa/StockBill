"""Supplier ledger (accounts payable): payments, reversals, balance sign,
running-balance statement and the printable export."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile
from inventory.models import (
    Product,
    PurchaseInvoice,
    Supplier,
    SupplierPayment,
    SupplierPaymentReversal,
    TaxRate,
)
from inventory.purchase_services import create_purchase
from inventory.services import get_default_warehouse
from inventory.supplier_ledger import (
    STATUS_ADVANCE,
    STATUS_PAYABLE,
    create_supplier_payment,
    supplier_balance,
    supplier_statement,
)

User = get_user_model()


class SupplierLedgerTestBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="ap_admin", password="StrongPass123!", role="admin")
        self.staff = User.objects.create_user(username="ap_staff", password="StrongPass123!", role="staff")
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        BusinessProfile.objects.create(
            business_name="Divya Test Enterprises", gstin="29ABCDE1234F1Z5", registered_address="Shop Road",
            state="Karnataka", state_code="29",
        )
        self.supplier = Supplier.objects.create(name="Chheda Foods", gstin="29AAACC1234D1Z5", state="Karnataka", state_code="29")
        self.other = Supplier.objects.create(name="Other Supplier", state_code="29")
        # 0% GST product so purchase totals equal quantity × rate exactly.
        self.tax = TaxRate.objects.create(name="Nil", rate=Decimal("0.00"))
        self.product = Product.objects.create(name="Chips", cost_price=10, tax=self.tax)

    def purchase(self, total, *, supplier=None, on=None, post=True):
        """Post a purchase whose total is exactly ``total`` (qty 1 × rate)."""
        return create_purchase(
            supplier=supplier or self.supplier,
            warehouse=get_default_warehouse(),
            invoice_date=on or date.today(),
            line_items=[{"product": self.product, "quantity": "1", "rate": str(total), "tax_rate": "0.00"}],
            created_by=self.admin,
            post=post,
        )


class SupplierPaymentApiTests(SupplierLedgerTestBase):
    def test_staff_records_a_payment_with_bank_transfer_by_default(self):
        response = self.client.post(
            "/api/supplier-payments/",
            {"supplier": self.supplier.pk, "amount": "100000.00", "reference": "UTR123"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["mode"], SupplierPayment.MODE_BANK_TRANSFER)
        self.assertEqual(response.data["payment_date"], date.today().isoformat())
        payment = SupplierPayment.objects.get(pk=response.data["id"])
        self.assertEqual(payment.amount, Decimal("100000.00"))
        self.assertEqual(payment.created_by, self.staff)

    def test_amount_must_be_positive_and_mode_valid(self):
        for amount in ["0", "-5"]:
            response = self.client.post("/api/supplier-payments/", {"supplier": self.supplier.pk, "amount": amount}, format="json")
            self.assertEqual(response.status_code, 400, amount)
        response = self.client.post(
            "/api/supplier-payments/", {"supplier": self.supplier.pk, "amount": "10", "mode": "CHEQUE"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SupplierPayment.objects.exists())

    def test_list_filters_by_supplier_and_date_range(self):
        old = create_supplier_payment(supplier=self.supplier, amount="10", created_by=self.staff, payment_date=date.today() - timedelta(days=10))
        recent = create_supplier_payment(supplier=self.supplier, amount="20", created_by=self.staff, mode=SupplierPayment.MODE_UPI)
        create_supplier_payment(supplier=self.other, amount="30", created_by=self.staff, mode=SupplierPayment.MODE_CASH)

        response = self.client.get("/api/supplier-payments/", {"supplier": self.supplier.pk})
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(sorted(ids), sorted([old.pk, recent.pk]))

        response = self.client.get(
            "/api/supplier-payments/",
            {"supplier": self.supplier.pk, "from": (date.today() - timedelta(days=1)).isoformat(), "to": date.today().isoformat()},
        )
        self.assertEqual([row["id"] for row in response.data["results"]], [recent.pk])
        self.assertEqual(response.data["results"][0]["mode_label"], "UPI")

        bad = self.client.get("/api/supplier-payments/", {"from": "27-11-2026"})
        self.assertEqual(bad.status_code, 400)

    def test_only_admin_can_reverse_and_reversal_is_capped(self):
        payment = create_supplier_payment(supplier=self.supplier, amount="500", created_by=self.staff)
        forbidden = self.client.post(f"/api/supplier-payments/{payment.pk}/reverse/", {"amount": "500", "reason": "dup"}, format="json")
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(self.admin)
        no_reason = self.client.post(f"/api/supplier-payments/{payment.pk}/reverse/", {"amount": "100"}, format="json")
        self.assertEqual(no_reason.status_code, 400)
        partial = self.client.post(f"/api/supplier-payments/{payment.pk}/reverse/", {"amount": "200", "reason": "Bounced part"}, format="json")
        self.assertEqual(partial.status_code, 201, partial.data)
        too_much = self.client.post(f"/api/supplier-payments/{payment.pk}/reverse/", {"amount": "300.01", "reason": "x"}, format="json")
        self.assertEqual(too_much.status_code, 400)
        rest = self.client.post(f"/api/supplier-payments/{payment.pk}/reverse/", {"amount": "300", "reason": "Rest"}, format="json")
        self.assertEqual(rest.status_code, 201)
        self.assertEqual(SupplierPaymentReversal.objects.filter(payment=payment).count(), 2)
        listed = self.client.get(f"/api/supplier-payments/{payment.pk}/").data
        self.assertEqual(Decimal(str(listed["reversed_amount"])), Decimal("500.00"))
        self.assertEqual(supplier_balance(self.supplier), Decimal("0.00"))


class SupplierPaymentImmutabilityTests(SupplierLedgerTestBase):
    def test_payments_cannot_be_edited_or_deleted(self):
        payment = create_supplier_payment(supplier=self.supplier, amount="50", created_by=self.staff)
        payment.amount = Decimal("60")
        with self.assertRaises(ValueError):
            payment.save()
        with self.assertRaises(ValueError):
            payment.delete()

    def test_reversals_cannot_be_edited_or_deleted(self):
        payment = create_supplier_payment(supplier=self.supplier, amount="50", created_by=self.staff)
        reversal = SupplierPaymentReversal.objects.create(payment=payment, amount=Decimal("5"), reason="r", reversed_by=self.admin)
        with self.assertRaises(ValueError):
            reversal.save()
        with self.assertRaises(ValueError):
            reversal.delete()

    def test_database_trigger_blocks_update_and_delete(self):
        payment = create_supplier_payment(supplier=self.supplier, amount="50", created_by=self.staff)
        for statement in (
            lambda: SupplierPayment.objects.filter(pk=payment.pk).update(amount=Decimal("1")),
            lambda: SupplierPayment.objects.filter(pk=payment.pk).delete(),
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    statement()
        self.assertEqual(SupplierPayment.objects.get(pk=payment.pk).amount, Decimal("50.00"))

    def test_database_check_rejects_non_positive_amount(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                SupplierPayment.objects.create(supplier=self.supplier, amount=Decimal("0"), created_by=self.staff)


class SupplierBalanceTests(SupplierLedgerTestBase):
    def test_round_advance_drawn_down_by_odd_purchase_leaves_the_right_advance(self):
        create_supplier_payment(supplier=self.supplier, amount="100000.00", created_by=self.staff)
        self.assertEqual(supplier_balance(self.supplier), Decimal("-100000.00"))
        self.purchase("97368.00")
        balance = supplier_balance(self.supplier)
        self.assertEqual(balance, Decimal("-2632.00"))
        statement = supplier_statement(self.supplier)
        self.assertEqual(statement["closing_status"], STATUS_ADVANCE)
        self.assertEqual(statement["current_balance"], Decimal("-2632.00"))

    def test_unpaid_purchase_is_payable(self):
        self.purchase("1234.56")
        self.assertEqual(supplier_balance(self.supplier), Decimal("1234.56"))
        self.assertEqual(supplier_statement(self.supplier)["closing_status"], STATUS_PAYABLE)

    def test_drafts_cancelled_purchases_and_other_suppliers_do_not_count(self):
        self.purchase("100.00", post=False)
        cancelled = self.purchase("200.00")
        from inventory.purchase_services import cancel_purchase

        cancel_purchase(purchase_id=cancelled.pk, cancelled_by=self.admin, reason="wrong bill")
        self.purchase("300.00", supplier=self.other)
        create_supplier_payment(supplier=self.other, amount="999", created_by=self.staff)
        self.assertEqual(PurchaseInvoice.objects.filter(supplier=self.supplier).count(), 2)
        self.assertEqual(supplier_balance(self.supplier), Decimal("0.00"))

    def test_reversal_restores_the_payable(self):
        self.purchase("1000.00")
        payment = create_supplier_payment(supplier=self.supplier, amount="1000", created_by=self.staff)
        self.assertEqual(supplier_balance(self.supplier), Decimal("0.00"))
        SupplierPaymentReversal.objects.create(payment=payment, amount=Decimal("400"), reason="bounced", reversed_by=self.admin)
        self.assertEqual(supplier_balance(self.supplier), Decimal("400.00"))


class SupplierStatementTests(SupplierLedgerTestBase):
    def setUp(self):
        super().setUp()
        self.d1 = date.today() - timedelta(days=20)
        self.d2 = date.today() - timedelta(days=10)
        self.d3 = date.today() - timedelta(days=5)
        # Same-day purchase and payment: the purchase is listed first.
        self.p1 = self.purchase("97368.00", on=self.d2)
        self.pay1 = create_supplier_payment(supplier=self.supplier, amount="100000", created_by=self.staff, payment_date=self.d1, reference="ADV-1")
        self.pay2 = create_supplier_payment(supplier=self.supplier, amount="5000", created_by=self.staff, payment_date=self.d2, mode=SupplierPayment.MODE_CASH)
        self.p2 = self.purchase("10000.50", on=self.d3)

    def test_entries_are_chronological_with_a_running_balance(self):
        statement = supplier_statement(self.supplier)
        kinds = [(e["kind"], e["date"]) for e in statement["entries"]]
        self.assertEqual(kinds, [
            ("payment", self.d1),
            ("purchase", self.d2),
            ("payment", self.d2),
            ("purchase", self.d3),
        ])
        balances = [e["balance"] for e in statement["entries"]]
        self.assertEqual(balances, [Decimal("-100000.00"), Decimal("-2632.00"), Decimal("-7632.00"), Decimal("2368.50")])
        self.assertEqual(statement["entries"][0]["debit"], Decimal("100000.00"))
        self.assertIsNone(statement["entries"][0]["credit"])
        self.assertEqual(statement["entries"][1]["credit"], Decimal("97368.00"))
        self.assertEqual(statement["total_credit"], Decimal("107368.50"))
        self.assertEqual(statement["total_debit"], Decimal("105000.00"))
        self.assertEqual(statement["closing_balance"], Decimal("2368.50"))
        self.assertEqual(statement["closing_status"], STATUS_PAYABLE)
        self.assertEqual(statement["closing_balance"], supplier_balance(self.supplier))

    def test_date_filter_brings_earlier_entries_forward(self):
        statement = supplier_statement(self.supplier, from_date=self.d2, to_date=self.d2)
        self.assertEqual(statement["opening_balance"], Decimal("-100000.00"))
        self.assertEqual(statement["opening_status"], STATUS_ADVANCE)
        self.assertEqual([e["kind"] for e in statement["entries"]], ["purchase", "payment"])
        self.assertEqual(statement["closing_balance"], Decimal("-7632.00"))
        # The all-time position is still reported.
        self.assertEqual(statement["current_balance"], Decimal("2368.50"))

    def test_ledger_endpoint(self):
        response = self.client.get(f"/api/suppliers/{self.supplier.pk}/ledger/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["supplier"]["name"], "Chheda Foods")
        self.assertEqual(len(response.data["entries"]), 4)
        self.assertEqual(response.data["closing_status"], STATUS_PAYABLE)
        self.assertEqual(Decimal(str(response.data["closing_balance"])), Decimal("2368.50"))
        self.assertIn("Payable", response.data["sign_convention"])
        self.assertEqual(response.data["entries"][2]["mode_label"], "Cash")

        filtered = self.client.get(f"/api/suppliers/{self.supplier.pk}/ledger/", {"from": self.d3.isoformat()})
        self.assertEqual(len(filtered.data["entries"]), 1)
        self.assertEqual(Decimal(str(filtered.data["opening_balance"])), Decimal("-7632.00"))
        self.assertEqual(self.client.get(f"/api/suppliers/{self.supplier.pk}/ledger/", {"to": "bad"}).status_code, 400)
        self.assertEqual(self.client.get("/api/suppliers/999999/ledger/").status_code, 404)

    def test_reversal_appears_as_a_credit_entry(self):
        SupplierPaymentReversal.objects.create(payment=self.pay2, amount=Decimal("5000"), reason="Wrong supplier", reversed_by=self.admin)
        statement = supplier_statement(self.supplier)
        reversal = [e for e in statement["entries"] if e["kind"] == "payment_reversal"][0]
        self.assertEqual(reversal["credit"], Decimal("5000.00"))
        self.assertEqual(statement["closing_balance"], Decimal("7368.50"))
        payment_entry = [e for e in statement["entries"] if e["kind"] == "payment" and e["id"] == self.pay2.pk][0]
        self.assertEqual(payment_entry["reversible_amount"], Decimal("0.00"))

    def test_printable_statement_export(self):
        from openpyxl import load_workbook

        response = self.client.get(f"/api/suppliers/{self.supplier.pk}/ledger/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment;", response["Content-Disposition"])
        sheet = load_workbook(BytesIO(response.content)).active
        values = [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
        flat = [str(v) for row in values for v in row if v is not None]
        self.assertEqual(values[0][0], "Divya Test Enterprises")
        self.assertIn("SUPPLIER STATEMENT", flat)
        self.assertIn("Chheda Foods", flat)
        self.assertIn("29AAACC1234D1Z5", flat)
        closing = [row for row in values if row[1] == "CLOSING"][0]
        self.assertEqual(Decimal(str(closing[5])), Decimal("2368.5"))
        self.assertEqual(closing[6], "2,368.50 Payable")
        entry_rows = [row for row in values if row[1] in {"Purchase", "Payment"}]
        self.assertEqual([Decimal(str(row[5])) for row in entry_rows], [Decimal("-100000"), Decimal("-2632"), Decimal("-7632"), Decimal("2368.5")])
        self.assertEqual(entry_rows[0][6], "100,000.00 Advance")


class SupplierReturnLedgerTests(SupplierLedgerTestBase):
    """Damaged goods back to the supplier, then a 1:1 replacement: net zero."""

    def test_return_is_a_debit_and_its_replacement_nets_it_to_zero(self):
        from inventory.services import get_damaged_warehouse
        from inventory.supplier_return_services import receive_replacement, return_to_supplier
        from inventory.transfer_services import post_warehouse_transfer

        self.purchase("80.00")  # 1 piece at 80 into Main
        self.assertEqual(supplier_balance(self.supplier), Decimal("80.00"))
        # Hold the piece in Damaged, as a damaged credit note would.
        post_warehouse_transfer(
            product=self.product, source_warehouse=get_default_warehouse(), destination_warehouse=get_damaged_warehouse(),
            quantity=Decimal("1"), unit="piece", reason="Damaged", effective_date=date.today(), created_by=self.admin,
        )
        supplier_return = return_to_supplier(supplier=self.supplier, product=self.product, quantity="1", created_by=self.admin)
        self.assertEqual(supplier_return.value, Decimal("80.00"))
        self.assertEqual(supplier_balance(self.supplier), Decimal("0.00"))

        receive_replacement(supplier_return=supplier_return, quantity="1", created_by=self.admin)
        self.assertEqual(supplier_balance(self.supplier), Decimal("80.00"))

        statement = supplier_statement(self.supplier)
        kinds = [e["kind"] for e in statement["entries"]]
        self.assertEqual(kinds, ["purchase", "supplier_return", "replacement"])
        returned = statement["entries"][1]
        replaced = statement["entries"][2]
        self.assertEqual(returned["debit"], Decimal("80.00"))
        self.assertEqual(replaced["credit"], Decimal("80.00"))
        self.assertEqual([e["balance"] for e in statement["entries"]], [Decimal("80.00"), Decimal("0.00"), Decimal("80.00")])
        self.assertEqual(statement["closing_balance"], Decimal("80.00"))
