from decimal import Decimal

from django.conf import settings
from django.db import models

from customers.models import Customer
from inventory.models import Product


class Invoice(models.Model):
    PAYMENT_STATUS_PAID = "paid"
    PAYMENT_STATUS_CREDIT = "credit"
    PAYMENT_STATUS_PARTIALLY_PAID = "partially_paid"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_PAID, "Paid"),
        (PAYMENT_STATUS_CREDIT, "Credit"),
        (PAYMENT_STATUS_PARTIALLY_PAID, "Partially Paid"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField(auto_now_add=True)
    payment_status = models.CharField(max_length=25, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_CREDIT)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_number

    @property
    def computed_payment_status(self):
        total_paid = sum((payment.amount for payment in self.payments.all()), Decimal("0.00"))
        if total_paid >= self.total_amount:
            return self.PAYMENT_STATUS_PAID
        if total_paid <= 0:
            return self.PAYMENT_STATUS_CREDIT
        return self.PAYMENT_STATUS_PARTIALLY_PAID


class InvoiceLineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="invoice_line_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    rate_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.PositiveIntegerField(default=18)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product.name}"


class CreditNote(models.Model):
    original_invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="credit_notes")
    reason = models.CharField(max_length=255, blank=True)
    note_date = models.DateField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_credit_notes")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CreditNote for {self.original_invoice.invoice_number}"


class CreditNoteLineItem(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="line_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="credit_note_line_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    rate_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.PositiveIntegerField(default=18)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.credit_note.id} - {self.product.name}"


class Payment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name} - {self.amount}"
