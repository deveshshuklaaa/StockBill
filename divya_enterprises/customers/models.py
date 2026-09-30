from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum


class Customer(models.Model):
    GST_REGISTRATION_UNREGISTERED = "unregistered"
    GST_REGISTRATION_REGISTERED = "registered"
    GST_REGISTRATION_CHOICES = [
        (GST_REGISTRATION_UNREGISTERED, "Unregistered"),
        (GST_REGISTRATION_REGISTERED, "Registered"),
    ]
    CUSTOMER_TYPE_B2B = "B2B"
    CUSTOMER_TYPE_B2C = "B2C"
    CUSTOMER_TYPE_CHOICES = [
        (CUSTOMER_TYPE_B2B, "B2B"),
        (CUSTOMER_TYPE_B2C, "B2C"),
    ]

    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=255, blank=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=10, blank=True)
    pincode = models.CharField(max_length=20, blank=True)
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPE_CHOICES, default=CUSTOMER_TYPE_B2C)
    gst_registration_type = models.CharField(max_length=20, choices=GST_REGISTRATION_CHOICES, default=GST_REGISTRATION_UNREGISTERED)
    gstin = models.CharField(max_length=25, blank=True, null=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit_days = models.PositiveIntegerField(default=0)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_regular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def outstanding_balance(self):
        invoice_total = self.invoices.filter(state="POSTED").aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        payment_total = self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        reversal_total = self.payments.aggregate(total=Sum("reversals__amount"))["total"] or Decimal("0.00")
        credit_note_total = self.invoices.aggregate(total=Sum("credit_notes__total_amount"))["total"] or Decimal("0.00")
        debit_note_total = self.debit_notes.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return self.opening_balance + invoice_total + debit_note_total - payment_total + reversal_total - credit_note_total

    @property
    def available_credit(self):
        return self.credit_limit - self.outstanding_balance


class CustomerMRPPricing(models.Model):
    """Customer-specific selling rate fixed per MRP slab."""

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="mrp_pricings"
    )
    mrp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    rate_per_piece = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mrp"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "mrp"],
                name="unique_customer_mrp_pricing",
            )
        ]

    def __str__(self):
        return f"{self.customer.name} - MRP ₹{self.mrp}: ₹{self.rate_per_piece}/pc"
