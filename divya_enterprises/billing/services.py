from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from rest_framework import serializers

from customers.models import Customer
from inventory.models import InventoryBalance, Product, StockLedger
from inventory.services import adjust_inventory, ensure_inventory_balance, get_default_warehouse

from .models import CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem, Payment


MONEY_QUANTUM = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _validate_invoice_lines(line_items):
    product_ids = {item["product"].pk for item in line_items}
    products = Product.objects.select_for_update().in_bulk(product_ids)
    warehouse = get_default_warehouse()
    balances = {}
    for product_id in product_ids:
        balance = ensure_inventory_balance(product=products[product_id], warehouse=warehouse)
        balances[product_id] = InventoryBalance.objects.select_for_update().get(pk=balance.pk)
    requested_stock = defaultdict(lambda: Decimal("0"))

    for item in line_items:
        product = products[item["product"].pk]
        if not product.is_active:
            raise serializers.ValidationError({"line_items": f"{product.name} is inactive and cannot be sold."})
        quantity = Decimal(item["quantity"])
        rate = Decimal(item["rate_charged"])
        tax_rate = item.get("tax_rate")
        if quantity <= 0:
            raise serializers.ValidationError({"line_items": "Quantity must be greater than zero."})
        if rate < 0:
            raise serializers.ValidationError({"line_items": "Rate charged cannot be negative."})
        if tax_rate is not None and int(tax_rate) != product.tax_slab:
            raise serializers.ValidationError(
                {"line_items": f"Tax rate for {product.name} must match its product tax slab of {product.tax_slab}%."}
            )
        requested_stock[product.pk] += quantity

    for product_id, quantity in requested_stock.items():
        product = products[product_id]
        available = balances.get(product_id).quantity_on_hand if product_id in balances else Decimal("0.000")
        if quantity > available:
            raise serializers.ValidationError(
                {"line_items": f"Insufficient stock for {product.name}. Available: {available}."}
            )

    return products


@transaction.atomic
def create_invoice(*, customer, invoice_number, notes="", created_by, payment_type, line_items):
    if payment_type == "credit" and customer is None:
        raise serializers.ValidationError({"customer": "A registered customer is required for credit invoices."})
    if customer is not None:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)

    products = _validate_invoice_lines(line_items)
    calculated_lines = []
    total_amount = Decimal("0.00")
    for item in line_items:
        product = products[item["product"].pk]
        quantity = Decimal(item["quantity"])
        rate = Decimal(item["rate_charged"])
        tax_rate = int(item.get("tax_rate") if item.get("tax_rate") is not None else product.tax_slab)
        subtotal = _money(quantity * rate)
        tax_amount = _money(subtotal * Decimal(tax_rate) / Decimal("100"))
        line_total = _money(subtotal + tax_amount)
        cogs_amount = _money(quantity * product.cost_price)
        calculated_lines.append((product, quantity, rate, tax_rate, tax_amount, line_total, cogs_amount))
        total_amount += line_total

    if payment_type == "credit" and customer is not None and customer.credit_limit:
        if customer.outstanding_balance + _money(total_amount) > customer.credit_limit:
            raise serializers.ValidationError(
                {"customer": f"Credit limit exceeded. Available credit: {_money(customer.credit_limit - customer.outstanding_balance)}."}
            )

    invoice = Invoice.objects.create(
        customer=customer,
        invoice_number=invoice_number,
        payment_type=payment_type,
        notes=notes,
        created_by=created_by,
        total_amount=_money(total_amount),
    )

    for product, quantity, rate, tax_rate, tax_amount, line_total, cogs_amount in calculated_lines:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            rate_charged=rate,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            line_total=line_total,
            cost_price_snapshot=product.cost_price,
            cogs_amount=cogs_amount,
        )
        adjust_inventory(
            product=product,
            quantity_delta=-quantity,
            movement_type=StockLedger.SALE,
            created_by=created_by,
            reference_type="invoice",
            reference_id=invoice.pk,
            unit_cost=product.cost_price,
        )

    if payment_type == "cash":
        Payment.objects.create(customer=customer, invoice=invoice, amount=invoice.total_amount)
    else:
        invoice.refresh_from_db()

    return invoice


@transaction.atomic
def create_credit_note(*, original_invoice, reason="", created_by, line_items):
    invoice = Invoice.objects.select_for_update().get(pk=original_invoice.pk)
    original_lines = {
        line.pk: line
        for line in invoice.line_items.select_related("product").all()
    }
    product_ids = {item["product"].pk for item in line_items}
    products = Product.objects.select_for_update().in_bulk(product_ids)
    already_reversed = defaultdict(lambda: Decimal("0"))
    for reversal in CreditNoteLineItem.objects.filter(credit_note__original_invoice=invoice):
        already_reversed[reversal.invoice_line_item_id] += reversal.quantity

    calculated_lines = []
    total_amount = Decimal("0.00")
    for item in line_items:
        original_line = original_lines.get(item.get("invoice_line_item").pk if item.get("invoice_line_item") else None)
        if original_line is None or original_line.product_id != item["product"].pk:
            raise serializers.ValidationError({"line_items": "Each reversal must reference its original invoice line item and product."})
        quantity = Decimal(item["quantity"])
        if quantity <= 0 or already_reversed[original_line.pk] + quantity > original_line.quantity:
            raise serializers.ValidationError({"line_items": "A reversal cannot exceed the quantity originally billed."})
        product = products[original_line.product_id]
        tax_rate = original_line.tax_rate
        subtotal = _money(quantity * original_line.rate_charged)
        tax_amount = _money(subtotal * Decimal(tax_rate) / Decimal("100"))
        line_total = _money(subtotal + tax_amount)
        calculated_lines.append((original_line, product, quantity, tax_amount, line_total))
        total_amount += line_total

    credit_note = CreditNote.objects.create(
        original_invoice=invoice,
        reason=reason,
        total_amount=_money(total_amount),
        created_by=created_by,
    )
    for original_line, product, quantity, tax_amount, line_total in calculated_lines:
        CreditNoteLineItem.objects.create(
            credit_note=credit_note,
            invoice_line_item=original_line,
            product=product,
            quantity=quantity,
            rate_charged=original_line.rate_charged,
            tax_rate=original_line.tax_rate,
            tax_amount=tax_amount,
            line_total=line_total,
        )
        adjust_inventory(
            product=product,
            quantity_delta=quantity,
            movement_type=StockLedger.SALES_RETURN,
            created_by=created_by,
            reference_type="credit_note",
            reference_id=credit_note.pk,
            unit_cost=product.cost_price,
        )

    return credit_note
