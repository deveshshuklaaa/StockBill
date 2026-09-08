from decimal import Decimal
import hashlib
import json

from django.http import HttpResponse
from django.template import Context, Template
from django.utils.text import slugify
from django.db import IntegrityError, transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

try:
    from weasyprint import HTML
except OSError:
    HTML = None

from accounts.permissions import IsAdminUser
from .models import CreditNote, Invoice, InvoiceIdempotencyKey, InvoiceLineItem, Payment
from .serializers import CreditNoteSerializer, InvoiceSerializer, PaymentSerializer
from .services import cancel_invoice, post_invoice, reverse_payment


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
        context = {
            "invoice": invoice,
            "line_items": invoice.line_items.all(),
            "customer": invoice.customer,
            "customer_name": invoice.customer_name_snapshot,
            "total": invoice.total_amount,
        }
        template = Template(
            """
            <html>
              <body>
                <h1>Invoice {{ invoice.invoice_number }}</h1>
                {% if invoice.state == 'CANCELLED' %}<h2>CANCELLED</h2><p>{{ invoice.cancellation_reason }}</p>{% endif %}
                <p>Customer: {{ customer_name|default:'Walk-in' }}</p>
                <p>Date: {{ invoice.invoice_date }}</p>
                <table>
                  <thead>
                    <tr><th>Item</th><th>Qty</th><th>Rate</th><th>Tax</th><th>Total</th></tr>
                  </thead>
                  <tbody>
                    {% for item in line_items %}
                    <tr>
                      <td>{{ item.product_name_snapshot|default:item.product.name }}</td>
                      <td>{{ item.quantity }}</td>
                      <td>{{ item.rate_charged }}</td>
                      <td>{{ item.tax_rate }}%</td>
                      <td>{{ item.line_total }}</td>
                    </tr>
                    {% endfor %}
                  </tbody>
                </table>
                <p><strong>Grand Total:</strong> {{ total }}</p>
              </body>
            </html>
            """
        )
        html = template.render(Context(context))
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
