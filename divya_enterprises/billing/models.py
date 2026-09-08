from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from customers.models import Customer
from inventory.models import Product


class BusinessProfile(models.Model):
    business_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(max_length=25)
    registered_address = models.TextField()
    state = models.CharField(max_length=100)
    state_code = models.CharField(max_length=10)
    contact_details = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.business_name


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
    TAX_MODE_EXCLUSIVE = "exclusive"
    TAX_MODE_INCLUSIVE = "inclusive"
    TAX_MODE_CHOICES = [
        (TAX_MODE_EXCLUSIVE, "Exclusive"),
        (TAX_MODE_INCLUSIVE, "Inclusive"),
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
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_invoices")
    seller_business_name_snapshot = models.CharField(max_length=255, blank=True)
    seller_gstin_snapshot = models.CharField(max_length=25, blank=True)
    seller_address_snapshot = models.TextField(blank=True)
    seller_state_snapshot = models.CharField(max_length=100, blank=True)
    seller_state_code_snapshot = models.CharField(max_length=10, blank=True)
    customer_name_snapshot = models.CharField(max_length=255, blank=True)
    customer_gstin_snapshot = models.CharField(max_length=25, blank=True)
    customer_state_code_snapshot = models.CharField(max_length=10, blank=True)
    customer_registration_type_snapshot = models.CharField(max_length=20, blank=True)
    billing_address_snapshot = models.TextField(blank=True)
    shipping_address_snapshot = models.TextField(blank=True)
    state_snapshot = models.CharField(max_length=100, blank=True)
    pincode_snapshot = models.CharField(max_length=20, blank=True)
    place_of_supply = models.CharField(max_length=10, blank=True)
    tax_mode = models.CharField(max_length=10, choices=TAX_MODE_CHOICES, default=TAX_MODE_EXCLUSIVE)
    payment_status = models.CharField(max_length=25, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_CREDIT)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_number

    def delete(self, *args, **kwargs):
        if self.state != self.STATE_DRAFT:
            raise ValueError("Only draft invoices can be deleted.")
        return super().delete(*args, **kwargs)

    def sync_payment_status(self):
        self.payment_status = self.computed_payment_status

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.only(
                "payment_type", "customer_id", "total_amount", "state", "invoice_number"
            ).get(pk=self.pk)
            if self.state != stored.state and not getattr(self, "_allow_lifecycle_transition", False):
                raise ValueError("Invoice lifecycle transitions must use domain services.")
            if stored.state in {self.STATE_POSTED, self.STATE_CANCELLED}:
                immutable_fields = [
                    "payment_type", "customer_id", "total_amount", "invoice_number",
                    "customer_name_snapshot", "customer_gstin_snapshot", "billing_address_snapshot",
                    "shipping_address_snapshot", "state_snapshot", "pincode_snapshot",
                    "seller_business_name_snapshot", "seller_gstin_snapshot", "seller_address_snapshot",
                    "seller_state_snapshot", "seller_state_code_snapshot",
                    "customer_state_code_snapshot", "customer_registration_type_snapshot",
                    "place_of_supply", "tax_mode",
                ]
                if any(getattr(self, field) != getattr(stored, field) for field in immutable_fields):
                    raise ValueError("Posted and cancelled invoice financial fields are immutable.")
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
        total_reversed = PaymentReversal.objects.filter(payment__invoice=self).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_credited = self.credit_notes.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        net_paid = total_paid - total_reversed - total_credited
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
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    cost_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cogs_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    product_name_snapshot = models.CharField(max_length=255, blank=True)
    base_unit_snapshot = models.CharField(max_length=20, blank=True)
    hsn_sac_snapshot = models.CharField(max_length=50, blank=True)
    taxable_value_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.get(pk=self.pk)
            if stored.invoice.state != Invoice.STATE_DRAFT:
                immutable_fields = [
                    "invoice_id", "product_id", "quantity", "rate_charged", "discount_amount", "tax_rate",
                    "tax_amount", "cgst_rate", "cgst_amount", "sgst_rate", "sgst_amount", "igst_rate", "igst_amount",
                    "line_total", "cost_price_snapshot", "cogs_amount",
                    "product_name_snapshot", "base_unit_snapshot", "hsn_sac_snapshot", "taxable_value_snapshot",
                ]
                if any(getattr(self, field) != getattr(stored, field) for field in immutable_fields):
                    raise ValueError("Posted and cancelled invoice lines are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.invoice.state != Invoice.STATE_DRAFT:
            raise ValueError("Only draft invoice lines can be deleted.")
        return super().delete(*args, **kwargs)


class CreditNote(models.Model):
    original_invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="credit_notes")
    reason = models.CharField(max_length=255, blank=True)
    note_date = models.DateField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_credit_notes")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CreditNote for {self.original_invoice.invoice_number}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Credit notes are immutable after creation.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Credit notes cannot be deleted.")


class CreditNoteLineItem(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="line_items")
    invoice_line_item = models.ForeignKey(InvoiceLineItem, on_delete=models.PROTECT, related_name="credit_note_reversals")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="credit_note_line_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    rate_charged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.credit_note.id} - {self.product.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Credit note lines are immutable after creation.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Credit note lines cannot be deleted.")


class Payment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name if self.customer else 'Walk-in'} - {self.amount}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.only("customer_id", "invoice_id", "amount").get(pk=self.pk)
            if any(getattr(self, field) != getattr(stored, field) for field in ["customer_id", "invoice_id", "amount"]):
                raise ValueError("Payments are append-only and cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Payments are append-only and cannot be deleted.")


class PaymentReversal(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="reversals")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField()
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_reversals")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Payment reversals are immutable after creation.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Payment reversals cannot be deleted.")


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.PositiveBigIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit logs are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit logs cannot be deleted.")


class DebitNote(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="debit_notes")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="debit_notes")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_debit_notes")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Debit notes are immutable after creation.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Debit notes cannot be deleted.")


class InvoiceIdempotencyKey(models.Model):
    key = models.CharField(max_length=255, unique=True)
    request_hash = models.CharField(max_length=64, default="")
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
    if kwargs.get("created"):
        AuditLog.objects.create(user=instance.created_by, action="credit_note_created", entity_type="CreditNote", entity_id=instance.pk)


@receiver(post_delete, sender=CreditNote)
def update_invoice_payment_status_on_credit_note_delete(sender, instance, **kwargs):
    refresh_invoice_payment_status(instance.original_invoice)
