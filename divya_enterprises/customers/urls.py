from django.urls import path

from .views import (
    CustomerDetailView,
    CustomerListCreateView,
    CustomerMRPPricingDetailView,
    CustomerMRPPricingListCreateView,
    CustomerMRPPricingLookupView,
    CustomerReportView,
)

urlpatterns = [
    path("customers/", CustomerListCreateView.as_view(), name="customer-list-create"),
    path("customers/<int:pk>/", CustomerDetailView.as_view(), name="customer-detail"),
    path("customers/<int:pk>/report/", CustomerReportView.as_view(), name="customer-report"),
    path(
        "customers/<int:pk>/mrp-pricing/",
        CustomerMRPPricingListCreateView.as_view(),
        name="customer-mrp-pricing-list-create",
    ),
    path(
        "customers/<int:customer_pk>/mrp-pricing/<int:pk>/",
        CustomerMRPPricingDetailView.as_view(),
        name="customer-mrp-pricing-detail",
    ),
    path(
        "customers/<int:pk>/mrp-pricing/lookup/",
        CustomerMRPPricingLookupView.as_view(),
        name="customer-mrp-pricing-lookup",
    ),
]
