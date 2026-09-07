from decimal import Decimal

from django.db import models
from django.db.models import Sum


class Customer(models.Model):
    CUSTOMER_TYPE_B2B = "B2B"
    CUSTOMER_TYPE_B2C = "B2C"
    CUSTOMER_TYPE_CHOICES = [
        (CUSTOMER_TYPE_B2B, "B2B"),
        (CUSTOMER_TYPE_B2C, "B2C"),
    ]

    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=255, blank=True)
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPE_CHOICES, default=CUSTOMER_TYPE_B2C)
    gstin = models.CharField(max_length=25, blank=True, null=True)
    is_regular = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def outstanding_balance(self):
        invoice_total = self.invoices.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        payment_total = self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        credit_note_total = self.invoices.aggregate(total=Sum("credit_notes__total_amount"))["total"] or Decimal("0.00")
        return invoice_total - payment_total - credit_note_total
