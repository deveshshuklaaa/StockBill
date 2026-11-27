"""Supplier ledger API (accounts payable).

Permissions mirror the customer side exactly (billing.views):
- PaymentListCreateView / PaymentDetailView: IsAuthenticated (staff and admin)
- PaymentReverseView: IsAuthenticated + IsAdminUser
- SalesGstReportExportView: IsStaffUser
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminUser, IsStaffUser

from .models import Supplier, SupplierPayment
from .supplier_ledger import build_supplier_statement_xlsx, create_supplier_payment, reverse_supplier_payment, supplier_statement


def _parse_dates(params):
    parsed = {}
    for name in ("from", "to"):
        raw = (params.get(name) or "").strip()
        if raw:
            try:
                parsed[name] = date.fromisoformat(raw)
            except ValueError:
                raise ValidationError({name: [f"{name} must use YYYY-MM-DD format."]})
        else:
            parsed[name] = None
    return parsed["from"], parsed["to"]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    reversed_amount = serializers.SerializerMethodField()
    payment_date = serializers.DateField(required=False)

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "supplier", "supplier_name", "amount", "payment_date", "mode", "mode_label",
            "reference", "notes", "reversed_amount", "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = ["id", "supplier_name", "mode_label", "reversed_amount", "created_by", "created_by_username", "created_at"]

    def get_reversed_amount(self, obj):
        return sum((reversal.amount for reversal in obj.reversals.all()), Decimal("0.00"))

    def create(self, validated_data):
        return create_supplier_payment(created_by=self.context["request"].user, **validated_data)


class SupplierPaymentListCreateView(generics.ListCreateAPIView):
    serializer_class = SupplierPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            SupplierPayment.objects.select_related("supplier", "created_by")
            .prefetch_related("reversals")
            .order_by("-payment_date", "-id")
        )
        params = self.request.query_params or {}
        supplier = (params.get("supplier") or "").strip()
        if supplier:
            if not supplier.isdigit():
                raise ValidationError({"supplier": ["supplier must be a numeric id."]})
            queryset = queryset.filter(supplier_id=int(supplier))
        mode = (params.get("mode") or "").strip()
        if mode:
            if mode not in {choice[0] for choice in SupplierPayment.MODE_CHOICES}:
                raise ValidationError({"mode": ["mode must be BANK_TRANSFER, CASH or UPI."]})
            queryset = queryset.filter(mode=mode)
        from_date, to_date = _parse_dates(params)
        if from_date:
            queryset = queryset.filter(payment_date__gte=from_date)
        if to_date:
            queryset = queryset.filter(payment_date__lte=to_date)
        return queryset


class SupplierPaymentDetailView(generics.RetrieveAPIView):
    queryset = SupplierPayment.objects.select_related("supplier", "created_by").prefetch_related("reversals")
    serializer_class = SupplierPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]


class SupplierPaymentReverseView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"reason": "A reversal reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        get_object_or_404(SupplierPayment, pk=pk)
        try:
            reversal = reverse_supplier_payment(
                payment_id=pk,
                amount=request.data.get("amount"),
                reversed_by=request.user,
                reason=reason,
            )
        except (TypeError, ValueError, InvalidOperation):
            return Response({"amount": "A valid reversal amount is required."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"id": reversal.id, "payment": reversal.payment_id, "amount": reversal.amount, "reason": reversal.reason},
            status=status.HTTP_201_CREATED,
        )


class SupplierLedgerView(APIView):
    """Chronological statement with running balance; ?from= / ?to= optional."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        from_date, to_date = _parse_dates(request.query_params)
        return Response(supplier_statement(supplier, from_date, to_date))


class SupplierLedgerExportView(APIView):
    """Printable supplier statement (.xlsx), mirroring SalesGstReportExportView."""

    permission_classes = [IsStaffUser]

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        from_date, to_date = _parse_dates(request.query_params)
        statement = supplier_statement(supplier, from_date, to_date)
        xlsx_bytes = build_supplier_statement_xlsx(statement)
        stamp = (to_date or timezone.localdate()).strftime("%Y%m%d")
        filename = f"supplier-statement-{slugify(supplier.name) or supplier.pk}-{stamp}.xlsx"
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
