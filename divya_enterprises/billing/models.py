from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from customers.models import Customer
from inventory.models import Product


class Invoice(models.Model):
    STATE_DRAFT = "DRAFT"
    STATE_POSTED = "POSTED"
    STATE_CANCELLED = "CANCELLED"
    STATE_CHOICES = [(value, value.title()) for value in [STATE_DRAFT, STATE_POSTED, STATE_CANCELLED]]
    PAYMENT_TYPE_CASH = "cash"
    PAYMENT_TYPE_CREDIT = "credit"
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_CASH, "Cash"),
        (PAYMENT_TYPE_CREDIT, "Credit"),
    ]
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
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES, default=PAYMENT_TYPE_CREDIT)
    state = models.CharField(max_length=12, choices=STATE_CHOICES, default=STATE_POSTED)
    cancellation_reason = models.TextField(blank=True)
    payment_status = models.CharField(max_length=25, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_CREDIT)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_number

    def sync_payment_status(self):
        self.payment_status = self.computed_payment_status

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored_payment_type = type(self).objects.only("payment_type").get(pk=self.pk).payment_type
            if self.payment_type != stored_payment_type:
                raise ValueError("Invoice payment_type is immutable after creation.")
        if self.pk is None:
            self.payment_status = self.PAYMENT_STATUS_CREDIT
        else:
            self.payment_status = self.computed_payment_status
        super().save(*args, **kwargs)

    @property
    def computed_payment_status(self):
        if self.pk is None:
            return self.PAYMENT_STATUS_CREDIT
        total_paid = self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_credited = self.credit_notes.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        net_paid = total_paid - total_credited
        if net_paid >= self.total_amount:
            return self.PAYMENT_STATUS_PAID
        if net_paid <= 0:
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
    cost_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cogs_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
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
    invoice_line_item = models.ForeignKey(InvoiceLineItem, on_delete=models.PROTECT, related_name="credit_note_reversals")
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
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name} - {self.amount}"


class InvoiceIdempotencyKey(models.Model):
    key = models.CharField(max_length=255, unique=True)
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="idempotency_record")
    created_at = models.DateTimeField(auto_now_add=True)


def refresh_invoice_payment_status(invoice):
    if invoice is None:
        return
    invoice.sync_payment_status()
    invoice.save(update_fields=["payment_status", "updated_at"])


@receiver(post_save, sender=Payment)
def update_invoice_payment_status_on_payment_save(sender, instance, **kwargs):
    if instance.invoice_id:
        refresh_invoice_payment_status(instance.invoice)


@receiver(post_delete, sender=Payment)
def update_invoice_payment_status_on_payment_delete(sender, instance, **kwargs):
    if instance.invoice_id:
        refresh_invoice_payment_status(instance.invoice)


@receiver(post_save, sender=CreditNote)
def update_invoice_payment_status_on_credit_note_save(sender, instance, **kwargs):
    refresh_invoice_payment_status(instance.original_invoice)


@receiver(post_delete, sender=CreditNote)
def update_invoice_payment_status_on_credit_note_delete(sender, instance, **kwargs):
    refresh_invoice_payment_status(instance.original_invoice)
