"""Customer CSV exports: details (/api/customers/export/) and outstanding
amounts (/api/customers/export/outstanding/)."""

import codecs
import csv
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import AuditLog, BusinessProfile
from billing.services import create_credit_note, create_invoice, create_payment, reverse_payment
from customers.models import Customer
from inventory.models import Product, TaxRate
from inventory.services import ensure_inventory_balance

DETAIL_HEADERS = [
    "Name", "Phone", "Customer type", "GST registration", "GSTIN", "Address",
    "Shipping address", "State", "State code", "Pincode", "Credit limit",
    "Credit days", "Regular customer",
]
OUTSTANDING_HEADERS = ["Customer name", "Address", "Outstanding amount"]


def parse_csv(response):
    body = response.content
    assert body.startswith(codecs.BOM_UTF8), "CSV must start with a UTF-8 BOM"
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline="")))


class CustomerExportTests(APITestCase):
    DETAILS = "/api/customers/export/"
    OUTSTANDING = "/api/customers/export/outstanding/"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(username="exp-admin", password="P123!", role="admin")
        cls.staff = User.objects.create_user(username="exp-staff", password="P123!", role="staff")
        BusinessProfile.objects.create(
            business_name="Divya Enterprises", gstin="27ABCDE1234F1Z5",
            registered_address="Pune", state="Maharashtra", state_code="27",
        )
        tax = TaxRate.objects.create(name="GST 5 cust export", rate=Decimal("5.00"))
        cls.product = Product.objects.create(
            name="Chips", tax=tax, default_price=100, cost_price=60, current_stock=100,
            unit_type="piece", unit_conversion_factor=1,
        )
        ensure_inventory_balance(product=cls.product)

        cls.trader = Customer.objects.create(
            name="Agarwal Traders", contact_info="9820098200", customer_type="B2B",
            gst_registration_type="registered", gstin="27AABCU9603R1ZM",
            billing_address="Shop 4,\nMarket Road\nPune", shipping_address="Godown 1\r\nHadapsar",
            state="Maharashtra", state_code="27", pincode="411001",
            credit_limit=Decimal("50000"), credit_days=30, is_regular=True,
        )
        cls.hindi = Customer.objects.create(name="शर्मा किराना स्टोर", state_code="27", billing_address="कोथरूड, पुणे")
        cls.evil = Customer.objects.create(name='=HYPERLINK("http://x")', contact_info="+919820098200", state_code="27")
        cls.advance = Customer.objects.create(name="Advance Paid Co", state_code="27", opening_balance=Decimal("-1500.00"))
        cls.settled = Customer.objects.create(name="Zero Balance Mart", state_code="27")
        cls.archived = Customer.objects.create(name="Closed Shop", state_code="27", opening_balance=Decimal("250.00"), is_active=False)

        def line(qty):
            return [{
                "product": cls.product, "quantity": Decimal(qty), "rate_charged": Decimal("100"),
                "tax_rate": Decimal("5"), "discount_amount": Decimal("0"),
                "sales_unit_name": "piece", "conversion_factor": Decimal("1"),
            }]

        first = create_invoice(customer=cls.trader, created_by=cls.admin,
                               payment_type="credit", line_items=line(4), place_of_supply="27")
        create_invoice(customer=cls.trader, created_by=cls.admin,
                       payment_type="credit", line_items=line(2), place_of_supply="27")
        payment = create_payment(customer=cls.trader, invoice=first, amount=Decimal("200.00"), actor=cls.admin)
        reverse_payment(payment_id=payment.pk, amount=Decimal("50.00"), reversed_by=cls.admin, reason="bounced")
        invoice_line = first.line_items.get()
        create_credit_note(original_invoice=first, created_by=cls.admin, reason="return",
                           line_items=[{"invoice_line_item": invoice_line, "product": cls.product, "quantity": Decimal("1")}])

    def client_as(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def details(self, **params):
        response = self.client_as(self.admin).get(self.DETAILS, params)
        self.assertEqual(response.status_code, 200, response.content[:200])
        return parse_csv(response)

    def outstanding(self, **params):
        response = self.client_as(self.admin).get(self.OUTSTANDING, params)
        self.assertEqual(response.status_code, 200, response.content[:200])
        return parse_csv(response)

    # --- permissions -------------------------------------------------------
    def test_admin_only(self):
        for url in (self.DETAILS, self.OUTSTANDING):
            self.assertEqual(self.client_as(self.admin).get(url).status_code, 200, url)
            self.assertEqual(self.client_as(self.staff).get(url).status_code, 403, url)
            # This project's first authenticator is SessionAuthentication, so
            # DRF answers anonymous requests with 403 rather than 401.
            self.assertIn(self.client_as(None).get(url).status_code, {401, 403}, url)

    # --- details export ----------------------------------------------------
    def test_details_headers_and_values(self):
        response = self.client_as(self.admin).get(self.DETAILS)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertRegex(response["Content-Disposition"], r'attachment; filename="stockbill-customers-\d{8}-\d{4}\.csv"')
        rows = parse_csv(response)
        self.assertEqual(rows[0], DETAIL_HEADERS)
        trader = next(r for r in rows[1:] if r[0] == "Agarwal Traders")
        # Phone / state code / pincode are written as ="..." so Excel keeps them as text.
        self.assertEqual(trader, [
            "Agarwal Traders", '="9820098200"', "B2B", "Registered", "27AABCU9603R1ZM",
            "Shop 4,, Market Road, Pune", "Godown 1, Hadapsar", "Maharashtra", '="27"', '="411001"',
            "50000.00", "30", "Yes",
        ])
        self.assertFalse({"Outstanding balance", "Available credit", "Opening balance"} & set(rows[0]))

    def test_details_injection_and_unicode(self):
        rows = self.details()
        evil = next(r for r in rows[1:] if "HYPERLINK" in r[0])
        self.assertEqual(evil[0], "'=HYPERLINK(\"http://x\")")
        # A "+91" phone is a string literal inside ="...", so it is never evaluated.
        self.assertEqual(evil[1], '="+919820098200"')
        # Empty codes stay empty rather than becoming ="".
        self.assertEqual(evil[9], "")
        hindi = next(r for r in rows[1:] if r[0] == "शर्मा किराना स्टोर")
        self.assertEqual(hindi[5], "कोथरूड, पुणे")

    def test_details_filters(self):
        self.assertEqual([r[0] for r in self.details(is_active="false")[1:]], ["Closed Shop"])
        active = [r[0] for r in self.details(is_active="true")[1:]]
        self.assertNotIn("Closed Shop", active)
        self.assertEqual(len(active), Customer.objects.filter(is_active=True).count())
        self.assertEqual([r[0] for r in self.details(search="agarwal")[1:]], ["Agarwal Traders"])
        self.assertEqual(self.client_as(self.admin).get(self.DETAILS, {"is_active": "maybe"}).status_code, 400)

    def test_details_audit_log(self):
        self.details(is_active="true")
        log = AuditLog.objects.get(action="customers_exported")
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.metadata, {"row_count": Customer.objects.filter(is_active=True).count(), "filters": {"is_active": "true"}})

    # --- outstanding export ------------------------------------------------
    def test_outstanding_uses_model_property(self):
        self.trader.refresh_from_db()
        expected = self.trader.outstanding_balance
        # Two invoices, a payment, a partial reversal and a credit note all count.
        self.assertGreater(expected, 0)
        rows = self.outstanding()
        self.assertEqual(rows[0], OUTSTANDING_HEADERS)
        trader = next(r for r in rows[1:] if r[0] == "Agarwal Traders")
        self.assertEqual(trader, ["Agarwal Traders", "Shop 4,, Market Road, Pune", f"{expected:.2f}"])

    def test_outstanding_skips_zero_keeps_negative_numeric_and_sorts(self):
        rows = self.outstanding()[1:]
        names = [r[0] for r in rows]
        self.assertNotIn("Zero Balance Mart", names)
        self.assertNotIn("शर्मा किराना स्टोर", names)  # nothing owed
        self.assertEqual(names, sorted(names))
        advance = next(r for r in rows if r[0] == "Advance Paid Co")
        self.assertEqual(advance[2], "-1500.00")  # numeric column: no "'" prefix
        self.assertIn("Closed Shop", names)

    def test_outstanding_filters_and_audit(self):
        rows = self.outstanding(is_active="true")[1:]
        self.assertNotIn("Closed Shop", [r[0] for r in rows])
        log = AuditLog.objects.get(action="customer_outstanding_exported")
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.metadata, {"row_count": len(rows), "filters": {"is_active": "true"}})
