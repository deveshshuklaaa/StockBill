"""Damaged-returns flow: credit notes may send returned goods to a chosen
warehouse (the non-sellable Damaged / Quarantine one for damaged route
returns); without a destination they go back to Main exactly as before."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile, CreditNote
from customers.models import Customer
from inventory.models import InventoryBalance, Product, StockLedger, TaxRate, Warehouse
from inventory.services import (
    DAMAGED_WAREHOUSE_CODE,
    get_damaged_warehouse,
    get_default_warehouse,
    sellable_stock_total,
)


class DamagedReturnsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="damaged_admin", password="StrongPass123!", role="admin"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.route = Customer.objects.create(
            name="Van Sales - Route 1",
            customer_type=Customer.CUSTOMER_TYPE_B2C,
            state_code="29",
        )
        tax = TaxRate.objects.create(name="5%", rate=Decimal("5.00"))
        BusinessProfile.objects.create(
            business_name="Test Business", gstin="29TEST8888", registered_address="Addr",
            state="Karnataka", state_code="29",
        )
        self.product = Product.objects.create(
            name="Chips", default_price=100, cost_price=60, tax=tax, current_stock=100,
            low_stock_threshold=Decimal("95"),
        )
        self.main = get_default_warehouse()
        self.damaged = get_damaged_warehouse()
        response = self.client.post(
            "/api/invoices/",
            {
                "customer": self.route.pk,
                "payment_type": "credit",
                "place_of_supply": "29",
                "line_items": [{"product": self.product.pk, "quantity": "10", "rate_charged": "100.00", "tax_rate": "5.00"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.invoice = response.data
        self.line_id = response.data["line_items"][0]["id"]

    def qty(self, warehouse):
        balance = InventoryBalance.objects.filter(product=self.product, warehouse=warehouse).first()
        return balance.quantity_on_hand if balance else Decimal("0.000")

    def credit_note(self, quantity, **extra):
        payload = {
            "original_invoice": self.invoice["id"],
            "reason": "Route damaged pile",
            "line_items": [{"invoice_line_item": self.line_id, "product": self.product.pk, "quantity": str(quantity)}],
        }
        payload.update(extra)
        return self.client.post("/api/credit-notes/", payload, format="json")

    def test_damaged_warehouse_exists_and_is_not_sellable(self):
        warehouse = Warehouse.objects.get(code=DAMAGED_WAREHOUSE_CODE)
        self.assertEqual(warehouse.name, "Damaged / Quarantine")
        self.assertFalse(warehouse.is_sellable)
        self.assertTrue(self.main.is_sellable)
        data = self.client.get("/api/warehouses/").data
        listed = {row["code"]: row for row in data.get("results", data)}
        self.assertFalse(listed[DAMAGED_WAREHOUSE_CODE]["is_sellable"])

    def test_credit_note_to_damaged_holds_stock_there_not_in_main(self):
        response = self.credit_note(4, destination_warehouse=self.damaged.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["destination_warehouse"], self.damaged.pk)
        self.assertEqual(response.data["destination_warehouse_code"], DAMAGED_WAREHOUSE_CODE)
        self.assertEqual(self.qty(self.main), Decimal("90.000"))
        self.assertEqual(self.qty(self.damaged), Decimal("4.000"))
        note = CreditNote.objects.get(pk=response.data["id"])
        self.assertEqual(note.destination_warehouse_id, self.damaged.pk)
        movement = StockLedger.objects.get(reference_type="credit_note", reference_id=note.pk)
        self.assertEqual(movement.movement_type, StockLedger.SALES_RETURN)
        self.assertEqual(movement.warehouse_id, self.damaged.pk)

    def test_omitting_destination_returns_to_main_as_today(self):
        response = self.credit_note(4)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["destination_warehouse"])
        self.assertIsNone(CreditNote.objects.get(pk=response.data["id"]).destination_warehouse_id)
        self.assertEqual(self.qty(self.main), Decimal("94.000"))
        self.assertEqual(self.qty(self.damaged), Decimal("0.000"))
        movement = StockLedger.objects.get(reference_type="credit_note", reference_id=response.data["id"])
        self.assertEqual(movement.warehouse_id, self.main.pk)

    def test_inactive_destination_is_rejected(self):
        closed = Warehouse.objects.create(name="Closed", code="CLOSED", is_active=False)
        response = self.credit_note(1, destination_warehouse=closed.pk)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CreditNote.objects.exists())

    def test_damaged_stock_is_excluded_from_sellable_figures(self):
        self.credit_note(4, destination_warehouse=self.damaged.pk)
        self.product.refresh_from_db()
        # Product stock (products list, invoice "available", low stock) is sellable only.
        self.assertEqual(self.product.current_stock, Decimal("90.000"))
        self.assertEqual(sellable_stock_total(self.product), Decimal("90.000"))
        products = self.client.get(f"/api/products/{self.product.pk}/").data
        self.assertEqual(Decimal(products["current_stock"]), Decimal("90.000"))

        dashboard = self.client.get("/api/reports/dashboard/").data
        self.assertEqual(dashboard["inventory"]["total_value"], Decimal("90.000") * Decimal("60.00"))
        self.assertEqual(dashboard["held_stock"]["quantity"], Decimal("4.000"))
        self.assertEqual(dashboard["held_stock"]["product_count"], 1)
        # 90 sellable is at or below the threshold of 95 even though 94 exist.
        self.assertIn(self.product.pk, [row["id"] for row in dashboard["low_stock"]])

        report = self.client.get("/api/reports/inventory/").data
        # Still visible in the stock report, but split out of the sellable figure.
        self.assertEqual(report["quantity_on_hand"], Decimal("94.000"))
        self.assertEqual(report["sellable_quantity_on_hand"], Decimal("90.000"))
        self.assertEqual(report["held_quantity_on_hand"], Decimal("4.000"))
        rows = {row["warehouse_code"]: row for row in report["by_warehouse"]}
        self.assertFalse(rows[DAMAGED_WAREHOUSE_CODE]["is_sellable"])
        self.assertTrue(rows[self.main.code]["is_sellable"])

        summary = {row["code"]: row for row in self.client.get("/api/warehouses/summary/").data}
        self.assertFalse(summary[DAMAGED_WAREHOUSE_CODE]["is_sellable"])
        self.assertEqual(Decimal(summary[DAMAGED_WAREHOUSE_CODE]["total_quantity"]), Decimal("4.000"))

    def test_invoices_cannot_be_billed_from_a_non_sellable_warehouse(self):
        self.credit_note(4, destination_warehouse=self.damaged.pk)
        response = self.client.post(
            "/api/invoices/",
            {
                "customer": self.route.pk,
                "payment_type": "credit",
                "source_warehouse": self.damaged.pk,
                "line_items": [{"product": self.product.pk, "quantity": "1", "rate_charged": "100.00", "tax_rate": "5.00"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("source_warehouse", response.data)
        self.assertEqual(self.qty(self.damaged), Decimal("4.000"))

    def test_service_rejects_non_sellable_source(self):
        from billing.services import create_invoice
        from rest_framework.exceptions import ValidationError

        self.credit_note(4, destination_warehouse=self.damaged.pk)
        with self.assertRaises(ValidationError):
            create_invoice(
                customer=None, created_by=self.user, payment_type="cash",
                line_items=[{"product": self.product, "quantity": "1", "rate_charged": "100", "tax_rate": "5.00"}],
                source_warehouse=self.damaged,
            )
