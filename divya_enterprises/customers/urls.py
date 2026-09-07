from django.urls import path

from .views import CustomerDetailView, CustomerListCreateView, CustomerReportView

urlpatterns = [
    path("customers/", CustomerListCreateView.as_view(), name="customer-list-create"),
    path("customers/<int:pk>/", CustomerDetailView.as_view(), name="customer-detail"),
    path("customers/<int:pk>/report/", CustomerReportView.as_view(), name="customer-report"),
]
