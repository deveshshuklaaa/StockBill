from decimal import Decimal

from django.http import HttpResponse
from django.template import Context, Template
from django.utils.text import slugify
from rest_framework import generics, permissions, status
from rest_framework.response import Response

try:
    from weasyprint import HTML
except OSError:
    HTML = None

from .models import CreditNote, Invoice, InvoiceLineItem, Payment
from .serializers import CreditNoteSerializer, InvoiceSerializer, PaymentSerializer


class InvoiceListCreateView(generics.ListCreateAPIView):
    queryset = Invoice.objects.select_related("customer", "created_by").prefetch_related("line_items").all().order_by("-created_at")
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]


class InvoiceDetailView(generics.RetrieveAPIView):
    queryset = Invoice.objects.select_related("customer", "created_by").prefetch_related("line_items").all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]


class PaymentListCreateView(generics.ListCreateAPIView):
    queryset = Payment.objects.select_related("customer", "invoice").all().order_by("-created_at")
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]


class PaymentDetailView(generics.RetrieveUpdateDestroyAPIView):
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
            "total": invoice.total_amount,
        }
        template = Template(
            """
            <html>
              <body>
                <h1>Invoice {{ invoice.invoice_number }}</h1>
                <p>Customer: {{ customer.name|default:'Walk-in' }}</p>
                <p>Date: {{ invoice.invoice_date }}</p>
                <table>
                  <thead>
                    <tr><th>Item</th><th>Qty</th><th>Rate</th><th>Tax</th><th>Total</th></tr>
                  </thead>
                  <tbody>
                    {% for item in line_items %}
                    <tr>
                      <td>{{ item.product.name }}</td>
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
