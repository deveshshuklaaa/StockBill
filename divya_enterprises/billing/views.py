from decimal import Decimal
import hashlib
import json
from datetime import date

from django.db.models import Q
from django.http import HttpResponse
from django.utils.text import slugify
from django.db import IntegrityError, transaction
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

try:
    from weasyprint import HTML
except OSError:
    HTML = None

from accounts.permissions import IsAdminUser
from .models import AuditLog, BusinessProfile, CreditNote, Invoice, InvoiceIdempotencyKey, InvoiceLineItem, Payment
from .serializers import AuditLogSerializer, BusinessProfileSerializer, CreditNoteSerializer, InvoiceSerializer, PaymentSerializer
from .services import cancel_invoice, post_invoice, reverse_payment
from .pdf import render_invoice_html


class BusinessProfileView(generics.RetrieveUpdateAPIView):
    """Single-row business profile used by invoices and the tax engine.

    Admin-only for both read and write: the profile drives GST place-of-supply
    and invoice snapshots, so it is configuration rather than shop data.
    """

    serializer_class = BusinessProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get_object(self):
        profile = BusinessProfile.objects.first()
        if profile is None:
            profile = BusinessProfile.objects.create(
                business_name="",
                gstin="",
                registered_address="",
                state="",
                state_code="",
            )
        return profile

    def perform_update(self, serializer):
        serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="business_profile_updated",
            entity_type="BusinessProfile",
            entity_id=serializer.instance.pk,
        )


class AuditLogListView(generics.ListAPIView):
    """Admin-only, read-only audit trail with server-side filters."""

    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user").all()
        params = self.request.query_params or {}
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(action__icontains=search)
                | Q(entity_type__icontains=search)
                | Q(user__username__icontains=search)
            )
        entity_type = (params.get("entity_type") or "").strip()
        if entity_type:
            queryset = queryset.filter(entity_type__iexact=entity_type)
        action = (params.get("action") or "").strip()
        if action:
            queryset = queryset.filter(action__iexact=action)
        from_date = (params.get("from") or "").strip()
        to_date = (params.get("to") or "").strip()
        for name, raw in (("from", from_date), ("to", to_date)):
            if raw:
                try:
                    date.fromisoformat(raw)
                except ValueError:
                    raise ValidationError({name: [f"{name} must use YYYY-MM-DD format."]})
        if from_date:
            queryset = queryset.filter(created_at__date__gte=from_date)
        if to_date:
            queryset = queryset.filter(created_at__date__lte=to_date)
        return queryset


class InvoiceListCreateView(generics.ListCreateAPIView):
    queryset = Invoice.objects.select_related("customer", "created_by").prefetch_related("line_items").all().order_by("-created_at")
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return super().create(request, *args, **kwargs)
        request_hash = hashlib.sha256(
            json.dumps(request.data, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        existing = InvoiceIdempotencyKey.objects.select_related("invoice").filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return Response({"detail": "Idempotency-Key was already used with a different request."}, status=status.HTTP_409_CONFLICT)
            return Response(self.get_serializer(existing.invoice).data, status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                invoice = serializer.save()
                InvoiceIdempotencyKey.objects.create(key=idempotency_key, request_hash=request_hash, invoice=invoice)
        except IntegrityError:
            existing = InvoiceIdempotencyKey.objects.select_related("invoice").get(key=idempotency_key)
            if existing.request_hash != request_hash:
                return Response({"detail": "Idempotency-Key was already used with a different request."}, status=status.HTTP_409_CONFLICT)
            return Response(self.get_serializer(existing.invoice).data, status=status.HTTP_200_OK)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class InvoiceDetailView(generics.RetrieveAPIView):
    queryset = Invoice.objects.select_related("customer", "created_by").prefetch_related("line_items").all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]


class PaymentListCreateView(generics.ListCreateAPIView):
    queryset = Payment.objects.select_related("customer", "invoice").all().order_by("-created_at")
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]


class PaymentDetailView(generics.RetrieveAPIView):
    queryset = Payment.objects.select_related("customer", "invoice").all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]


class CreditNoteListCreateView(generics.ListCreateAPIView):
    queryset = CreditNote.objects.select_related("original_invoice", "created_by").prefetch_related("line_items").all().order_by("-created_at")
    serializer_class = CreditNoteSerializer
    permission_classes = [permissions.IsAuthenticated]


class CreditNoteDetailView(generics.RetrieveAPIView):
    queryset = CreditNote.objects.select_related("original_invoice", "created_by").prefetch_related("line_items").all()
    serializer_class = CreditNoteSerializer
    permission_classes = [permissions.IsAuthenticated]


class InvoicePdfView(generics.GenericAPIView):
    queryset = Invoice.objects.select_related("customer").prefetch_related("line_items__product").all()
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        if HTML is None:
            return Response(
                {"detail": "PDF generation is unavailable because the native WeasyPrint libraries are not installed on this system."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        invoice = self.get_object()
        html = render_invoice_html(invoice)
        pdf_bytes = HTML(string=html).write_pdf()
        filename = f"invoice-{slugify(invoice.invoice_number)}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class InvoiceCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"reason": "A cancellation reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        invoice = cancel_invoice(invoice_id=pk, cancelled_by=request.user, reason=reason)
        return Response(InvoiceSerializer(invoice).data)


class InvoiceDraftCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = InvoiceSerializer(data=request.data, context={"request": request, "invoice_state": Invoice.STATE_DRAFT})
        serializer.is_valid(raise_exception=True)
        return Response(InvoiceSerializer(serializer.save()).data, status=status.HTTP_201_CREATED)


class InvoicePostView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        invoice = post_invoice(invoice_id=pk, posted_by=request.user)
        return Response(InvoiceSerializer(invoice).data)


class PaymentReverseView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"reason": "A reversal reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reversal = reverse_payment(
                payment_id=pk,
                amount=request.data.get("amount"),
                reversed_by=request.user,
                reason=reason,
            )
        except (TypeError, ValueError):
            return Response({"amount": "A valid reversal amount is required."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": reversal.id, "payment": reversal.payment_id, "amount": reversal.amount, "reason": reversal.reason}, status=status.HTTP_201_CREATED)
