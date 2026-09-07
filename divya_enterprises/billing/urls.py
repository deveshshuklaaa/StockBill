from django.urls import path

from .views import (
    CreditNoteDetailView,
    CreditNoteListCreateView,
    InvoiceDetailView,
    InvoiceListCreateView,
    InvoicePdfView,
    PaymentDetailView,
    PaymentListCreateView,
)
from .reporting import DailySalesReportView, ProfitLossReportView, StockValuationReportView, TopProductsReportView

urlpatterns = [
    path("invoices/", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path("invoices/<int:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path("invoices/<int:pk>/pdf/", InvoicePdfView.as_view(), name="invoice-pdf"),
    path("credit-notes/", CreditNoteListCreateView.as_view(), name="credit-note-list-create"),
    path("credit-notes/<int:pk>/", CreditNoteDetailView.as_view(), name="credit-note-detail"),
    path("payments/", PaymentListCreateView.as_view(), name="payment-list-create"),
    path("payments/<int:pk>/", PaymentDetailView.as_view(), name="payment-detail"),
    path("reports/daily-sales/", DailySalesReportView.as_view(), name="daily-sales-report"),
    path("reports/stock-valuation/", StockValuationReportView.as_view(), name="stock-valuation-report"),
    path("reports/profit-loss/", ProfitLossReportView.as_view(), name="profit-loss-report"),
    path("reports/top-products/", TopProductsReportView.as_view(), name="top-products-report"),
]
