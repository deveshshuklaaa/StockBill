from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import Invoice, Payment
from billing.services import create_invoice
from customers.models import Customer
from .models import InventoryBalance, Product, StockLedger, Warehouse
from .services import adjust_inventory, get_default_warehouse, receive_purchase


class InventoryBalanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="inventory-admin",
            password="StrongPass123!",
            role="admin",
        )
        self.customer = Customer.objects.create(name="Inventory Customer")
        self.product = Product.objects.create(
            name="Ledger Product",
            unit_type=Product.UNIT_PIECE,
            base_unit=Product.UNIT_PIECE,
            unit_conversion_factor=1,
            default_price=100,
            cost_price=60,
            tax_slab=Product.TAX_18,
            current_stock=0,
        )
        self.warehouse = get_default_warehouse()

    def test_sale_and_return_create_ledger_events_and_update_balance(self):
        adjust_inventory(
            product=self.product,
            quantity_delta=Decimal("10.000"),
            movement_type=StockLedger.OPENING_STOCK,
            created_by=self.user,
        )
        invoice = create_invoice(
            customer=self.customer,
            invoice_number="INV-LEDGER-1",
            created_by=self.user,
            payment_type="credit",
            line_items=[
                {
                    "product": self.product,
                    "quantity": Decimal("3"),
                    "rate_charged": Decimal("100"),
                    "tax_rate": 18,
                }
            ],
        )
        balance = InventoryBalance.objects.get(product=self.product, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("7.000"))
        self.assertEqual(StockLedger.objects.filter(reference_type="invoice", reference_id=invoice.pk, movement_type=StockLedger.SALE).count(), 1)

        line = invoice.line_items.get()
        from billing.services import create_credit_note
        create_credit_note(
            original_invoice=invoice,
            reason="Return",
            created_by=self.user,
            line_items=[
                {
                    "invoice_line_item": line,
                    "product": self.product,
                    "quantity": Decimal("1"),
                }
            ],
        )
        balance.refresh_from_db()
        self.assertEqual(balance.quantity_on_hand, Decimal("8.000"))
        self.assertEqual(StockLedger.objects.filter(movement_type=StockLedger.SALES_RETURN).count(), 1)

    def test_oversell_is_rejected_without_ledger_or_balance_mutation(self):
        adjust_inventory(
            product=self.product,
            quantity_delta=Decimal("2.000"),
            movement_type=StockLedger.OPENING_STOCK,
            created_by=self.user,
        )
        with self.assertRaises(Exception):
            create_invoice(
                customer=self.customer,
                invoice_number="INV-LEDGER-OVER",
                created_by=self.user,
                payment_type="credit",
                line_items=[
                    {
                        "product": self.product,
                        "quantity": Decimal("3"),
                        "rate_charged": Decimal("100"),
                        "tax_rate": 18,
                    }
                ],
            )
        balance = InventoryBalance.objects.get(product=self.product, warehouse=self.warehouse)
        self.assertEqual(balance.quantity_on_hand, Decimal("2.000"))
        self.assertFalse(Invoice.objects.filter(invoice_number="INV-LEDGER-OVER").exists())
        self.assertEqual(StockLedger.objects.filter(movement_type=StockLedger.SALE).count(), 0)

    def test_inventory_balance_is_unique_per_product_and_warehouse(self):
        second = Warehouse.objects.create(name="Second Warehouse", code="SECOND")
        InventoryBalance.objects.create(product=self.product, warehouse=second, quantity_on_hand=Decimal("4"))
        self.assertEqual(self.product.inventory_balances.count(), 1)

    def test_purchase_receipt_updates_weighted_cost_balance_and_ledger(self):
        from .models import Supplier
        supplier = Supplier.objects.create(name="Test Supplier")
        purchase = receive_purchase(
            supplier=supplier,
            warehouse=self.warehouse,
            invoice_number="PURCHASE-1001",
            invoice_date="2026-09-08",
            created_by=self.user,
            line_items=[
                {"product": self.product, "quantity": Decimal("5"), "unit_cost": Decimal("80")}
            ],
        )
        balance = InventoryBalance.objects.get(product=self.product, warehouse=self.warehouse)
        self.assertEqual(purchase.total_amount, Decimal("400"))
        self.assertEqual(balance.quantity_on_hand, Decimal("5.000"))
        self.assertEqual(balance.average_cost, Decimal("80.00"))
        self.assertEqual(StockLedger.objects.filter(reference_id=purchase.pk, movement_type=StockLedger.PURCHASE).count(), 1)
