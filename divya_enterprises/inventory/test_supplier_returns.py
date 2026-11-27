"""Minimal supplier exit leg for damaged stock: out of Damaged to the
supplier, replacement into Main (1:1)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient, APITestCase

from billing.models import BusinessProfile
from billing.services import create_credit_note, create_invoice
from inventory.models import InventoryBalance, Product, StockLedger, Supplier, SupplierReturn, TaxRate
from inventory.purchase_services import create_purchase
from inventory.services import get_damaged_warehouse, get_default_warehouse

User = get_user_model()


class SupplierReturnTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="sr_admin", password="StrongPass123!", role="admin")
        self.staff = User.objects.create_user(username="sr_staff", password="StrongPass123!", role="staff")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        BusinessProfile.objects.create(business_name="B", gstin="29X", registered_address="A", state="K", state_code="29")
        self.supplier = Supplier.objects.create(name="Chheda Foods", state_code="29")
        tax = TaxRate.objects.create(name="Nil", rate=Decimal("0.00"))
        self.product = Product.objects.create(name="Chips", cost_price=7, tax=tax)
        self.main = get_default_warehouse()
        self.damaged = get_damaged_warehouse()
        # 50 bought at 8.00 each, 10 sold, 6 come back damaged.
        create_purchase(
            supplier=self.supplier, warehouse=self.main, invoice_date=date.today(),
            line_items=[{"product": self.product, "quantity": "50", "rate": "8.00", "tax_rate": "0.00"}],
            created_by=self.admin, post=True,
        )
        invoice = create_invoice(
            customer=None, created_by=self.admin, payment_type="cash",
            line_items=[{"product": self.product, "quantity": "10", "rate_charged": "10", "tax_rate": "0.00"}],
        )
        create_credit_note(
            original_invoice=invoice, reason="damaged", created_by=self.admin,
            line_items=[{"invoice_line_item": invoice.line_items.get(), "product": self.product, "quantity": "6"}],
            destination_warehouse=self.damaged,
        )

    def qty(self, warehouse):
        return InventoryBalance.objects.get(product=self.product, warehouse=warehouse).quantity_on_hand

    def send_back(self, quantity, **extra):
        payload = {"supplier": self.supplier.pk, "product": self.product.pk, "quantity": str(quantity)}
        payload.update(extra)
        return self.client.post("/api/supplier-returns/", payload, format="json")

    def test_return_leaves_damaged_and_replacement_lands_in_main(self):
        self.assertEqual(self.qty(self.main), Decimal("40.000"))
        self.assertEqual(self.qty(self.damaged), Decimal("6.000"))

        response = self.send_back(6, reference="CH-99")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["warehouse_code"], "DAMAGED")
        # Valued at the last purchase cost from this supplier.
        self.assertEqual(Decimal(str(response.data["unit_cost"])), Decimal("8.00"))
        self.assertEqual(Decimal(str(response.data["value"])), Decimal("48.00"))
        self.assertEqual(Decimal(str(response.data["outstanding_quantity"])), Decimal("6.000"))
        self.assertEqual(self.qty(self.damaged), Decimal("0.000"))
        self.assertEqual(self.qty(self.main), Decimal("40.000"))
        out = StockLedger.objects.get(reference_type="supplier_return", reference_id=response.data["id"])
        self.assertEqual(out.movement_type, StockLedger.PURCHASE_RETURN)
        self.assertEqual(out.warehouse_id, self.damaged.pk)
        self.assertEqual(out.quantity_delta, Decimal("-6.000"))

        return_id = response.data["id"]
        partial = self.client.post(f"/api/supplier-returns/{return_id}/replacements/", {"quantity": "4"}, format="json")
        self.assertEqual(partial.status_code, 201, partial.data)
        self.assertEqual(Decimal(str(partial.data["outstanding_quantity"])), Decimal("2.000"))
        self.assertEqual(self.qty(self.main), Decimal("44.000"))
        too_many = self.client.post(f"/api/supplier-returns/{return_id}/replacements/", {"quantity": "3"}, format="json")
        self.assertEqual(too_many.status_code, 400)
        rest = self.client.post(f"/api/supplier-returns/{return_id}/replacements/", {"quantity": "2"}, format="json")
        self.assertEqual(rest.status_code, 201)
        self.assertEqual(self.qty(self.main), Decimal("46.000"))
        receipt_movements = StockLedger.objects.filter(reference_type="supplier_replacement")
        self.assertEqual(receipt_movements.count(), 2)
        self.assertTrue(all(m.warehouse_id == self.main.pk for m in receipt_movements))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("46.000"))

    def test_cannot_return_more_than_the_damaged_warehouse_holds(self):
        response = self.send_back(7)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SupplierReturn.objects.exists())
        self.assertEqual(self.qty(self.damaged), Decimal("6.000"))

    def test_explicit_unit_cost_and_source_warehouse(self):
        response = self.send_back(5, unit_cost="7.50", warehouse=self.main.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(str(response.data["value"])), Decimal("37.50"))
        self.assertEqual(self.qty(self.main), Decimal("35.000"))
        self.assertEqual(self.qty(self.damaged), Decimal("6.000"))

    def test_staff_can_read_but_not_create(self):
        self.send_back(1)
        self.client.force_authenticate(self.staff)
        listed = self.client.get("/api/supplier-returns/", {"supplier": self.supplier.pk})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data["results"]), 1)
        self.assertEqual(self.send_back(1).status_code, 403)
        return_id = listed.data["results"][0]["id"]
        self.assertEqual(
            self.client.post(f"/api/supplier-returns/{return_id}/replacements/", {"quantity": "1"}, format="json").status_code,
            403,
        )

    def test_returns_are_append_only(self):
        supplier_return = SupplierReturn.objects.get(pk=self.send_back(2).data["id"])
        with self.assertRaises(ValueError):
            supplier_return.save()
        with self.assertRaises(ValueError):
            supplier_return.delete()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                SupplierReturn.objects.filter(pk=supplier_return.pk).update(quantity=Decimal("1"))
