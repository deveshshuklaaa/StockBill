from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminOrReadOnly
from billing.models import AuditLog, CreditNote, Payment
from .models import Customer
from .serializers import CustomerSerializer


class CustomerListCreateView(generics.ListCreateAPIView):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        # -id tiebreak: created_at shares a value across rows created in one
        # transaction/transactional test setup, so ordering needs a stable key.
        queryset = Customer.objects.all().order_by("-created_at", "-id")
        params = self.request.query_params or {}
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(contact_info__icontains=search)
                | Q(gstin__icontains=search)
            )
        status = (params.get("is_active") or "").strip().lower()
        if status:
            if status not in {"true", "false"}:
                raise ValidationError({"is_active": ["is_active must be 'true' or 'false'."]})
            queryset = queryset.filter(is_active=status == "true")
        return queryset

    def perform_create(self, serializer):
        customer = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="customer_created",
            entity_type="Customer",
            entity_id=customer.pk,
        )


class CustomerDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_update(self, serializer):
        customer = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="customer_updated",
            entity_type="Customer",
            entity_id=customer.pk,
        )

    def perform_destroy(self, instance):
        # Customers referenced by invoices (PROTECT), payments (PROTECT), or
        # debit notes (PROTECT) can never be deleted; archive instead so
        # historical documents stay intact, matching the supplier pattern.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        AuditLog.objects.create(
            user=self.request.user,
            action="customer_archived",
            entity_type="Customer",
            entity_id=instance.pk,
        )


def _customer_credit_notes(customer):
    return (
        CreditNote.objects.filter(original_invoice__customer=customer)
        .select_related("original_invoice")
        .order_by("note_date", "id")
    )


def _customer_statement(customer):
    """Authoritative running-balance ledger for a single customer.

    Debits increase what the customer owes (invoices, debit notes, payment
    reversals); credits decrease it (payments, credit notes). All rows and
    the running balance are computed here in the backend; the UI renders
    them verbatim.
    """
    rows = []

    if customer.opening_balance:
        opening = customer.opening_balance
        rows.append(
            {
                "date": None,
                "reference": "Opening balance",
                "type": "OPENING",
                "debit": opening if opening > 0 else None,
                "credit": -opening if opening < 0 else None,
                "kind": "opening",
            }
        )

    for invoice in customer.invoices.filter(state="POSTED").order_by("invoice_date", "id"):
        rows.append(
            {
                "date": invoice.invoice_date,
                "reference": invoice.invoice_number,
                "type": "INVOICE",
                "debit": invoice.total_amount,
                "credit": None,
                "kind": "invoice",
            }
        )

    for payment in customer.payments.order_by("payment_date", "id").prefetch_related("reversals"):
        rows.append(
            {
                "date": payment.payment_date,
                "reference": payment.invoice.invoice_number if payment.invoice_id else f"Payment #{payment.pk}",
                "type": "PAYMENT",
                "debit": None,
                "credit": payment.amount,
                "kind": "payment",
            }
        )
        for reversal in payment.reversals.all().order_by("id"):
            rows.append(
                {
                    "date": reversal.created_at.date(),
                    "reference": f"Reversal of payment #{payment.pk}",
                    "type": "PAYMENT_REVERSAL",
                    "debit": reversal.amount,
                    "credit": None,
                    "kind": "payment_reversal",
                }
            )

    for credit_note in _customer_credit_notes(customer):
        rows.append(
            {
                "date": credit_note.note_date,
                "reference": f"Credit note #{credit_note.pk} · {credit_note.original_invoice.invoice_number}",
                "type": "CREDIT_NOTE",
                "debit": None,
                "credit": credit_note.total_amount,
                "kind": "credit_note",
            }
        )

    for debit_note in customer.debit_notes.order_by("created_at", "id"):
        rows.append(
            {
                "date": debit_note.created_at.date(),
                "reference": f"Debit note #{debit_note.pk}",
                "type": "DEBIT_NOTE",
                "debit": debit_note.amount,
                "credit": None,
                "kind": "debit_note",
            }
        )

    kind_order = {
        "opening": 0,
        "invoice": 1,
        "credit_note": 2,
        "payment": 3,
        "payment_reversal": 4,
        "debit_note": 5,
    }
    rows.sort(key=lambda row: (
        row["date"] is None,
        row["date"] or customer.created_at.date(),
        kind_order[row["kind"]],
    ))

    balance = Decimal("0.00")
    for row in rows:
        balance += Decimal(row["debit"] or 0) - Decimal(row["credit"] or 0)
        row["balance"] = balance
    return rows


class CustomerReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        invoices = customer.invoices.order_by("-invoice_date", "-id").values(
            "id", "invoice_number", "invoice_date", "payment_status", "total_amount", "state", "payment_type"
        )
        payments = (
            Payment.objects.filter(customer=customer)
            .select_related("invoice")
            .prefetch_related("reversals")
            .order_by("-payment_date", "-id")
        )
        payment_rows = []
        for payment in payments:
            reversed_amount = payment.reversals.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            payment_rows.append(
                {
                    "id": payment.pk,
                    "invoice_id": payment.invoice_id,
                    "invoice_number": payment.invoice.invoice_number if payment.invoice_id else None,
                    "amount": payment.amount,
                    "reversed_amount": reversed_amount,
                    "payment_date": payment.payment_date,
                    "notes": payment.notes,
                }
            )
        statement = _customer_statement(customer)
        return Response(
            {
                "customer_id": customer.id,
                "customer_name": customer.name,
                "is_active": customer.is_active,
                "credit_limit": customer.credit_limit,
                "outstanding_balance": customer.outstanding_balance,
                "available_credit": customer.available_credit,
                "invoices": list(invoices),
                "payments": payment_rows,
                "statement": statement,
                "statement_closing_balance": statement[-1]["balance"] if statement else Decimal("0.00"),
            }
        )
