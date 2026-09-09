from django.urls import path

from .views import (
    AttributeChoiceDetailView,
    AttributeChoiceListCreateView,
    AttributeDefinitionDetailView,
    AttributeDefinitionListCreateView,
    CategoryAttributeDetailView,
    CategoryAttributeListCreateView,
    CategoryDetailView,
    CategoryListCreateView,
    CategorySchemaView,
    InventoryBalanceListView,
    ProductDetailView,
    ProductListCreateView,
    PurchaseInvoiceListCreateView,
    StockLedgerDetailView,
    StockLedgerListCreateView,
    SupplierDetailView,
    SupplierListCreateView,
    TaxRateListView,
    WarehouseDetailView,
    WarehouseListCreateView,
)

urlpatterns = [
    path("suppliers/", SupplierListCreateView.as_view(), name="supplier-list-create"),
    path("suppliers/<int:pk>/", SupplierDetailView.as_view(), name="supplier-detail"),
    path(
        "warehouses/", WarehouseListCreateView.as_view(), name="warehouse-list-create"
    ),
    path(
        "warehouses/<int:pk>/", WarehouseDetailView.as_view(), name="warehouse-detail"
    ),
    path("categories/", CategoryListCreateView.as_view(), name="category-list-create"),
    path("categories/<int:pk>/", CategoryDetailView.as_view(), name="category-detail"),
    path(
        "categories/<int:pk>/attributes/",
        CategorySchemaView.as_view(),
        name="category-attribute-schema",
    ),
    path(
        "attributes/",
        AttributeDefinitionListCreateView.as_view(),
        name="attribute-definition-list-create",
    ),
    path(
        "attributes/<int:pk>/",
        AttributeDefinitionDetailView.as_view(),
        name="attribute-definition-detail",
    ),
    path(
        "attribute-choices/",
        AttributeChoiceListCreateView.as_view(),
        name="attribute-choice-list-create",
    ),
    path(
        "attribute-choices/<int:pk>/",
        AttributeChoiceDetailView.as_view(),
        name="attribute-choice-detail",
    ),
    path(
        "categories/<int:category_pk>/attribute-assignments/",
        CategoryAttributeListCreateView.as_view(),
        name="category-attribute-assignment-list-create",
    ),
    path(
        "categories/<int:category_pk>/attribute-assignments/<int:pk>/",
        CategoryAttributeDetailView.as_view(),
        name="category-attribute-assignment-detail",
    ),
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path("tax-rates/", TaxRateListView.as_view(), name="tax-rate-list"),
    path(
        "stock-ledger/",
        StockLedgerListCreateView.as_view(),
        name="stock-ledger-list-create",
    ),
    path(
        "stock-ledger/<int:pk>/",
        StockLedgerDetailView.as_view(),
        name="stock-ledger-detail",
    ),
    path(
        "inventory-balances/",
        InventoryBalanceListView.as_view(),
        name="inventory-balance-list",
    ),
    path(
        "purchase-invoices/",
        PurchaseInvoiceListCreateView.as_view(),
        name="purchase-invoice-list-create",
    ),
]
