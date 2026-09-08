from django.urls import path

from .views import (
    ProductDetailView,
    ProductListCreateView,
    StockLedgerDetailView,
    StockLedgerListCreateView,
    SupplierDetailView,
    SupplierListCreateView,
    WarehouseDetailView,
    WarehouseListCreateView,
    InventoryBalanceListView,
    PurchaseInvoiceListCreateView,
)

urlpatterns = [
    path("suppliers/", SupplierListCreateView.as_view(), name="supplier-list-create"),
    path("suppliers/<int:pk>/", SupplierDetailView.as_view(), name="supplier-detail"),
    path("warehouses/", WarehouseListCreateView.as_view(), name="warehouse-list-create"),
    path("warehouses/<int:pk>/", WarehouseDetailView.as_view(), name="warehouse-detail"),
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path("stock-ledger/", StockLedgerListCreateView.as_view(), name="stock-ledger-list-create"),
    path("stock-ledger/<int:pk>/", StockLedgerDetailView.as_view(), name="stock-ledger-detail"),
    path("inventory-balances/", InventoryBalanceListView.as_view(), name="inventory-balance-list"),
    path("purchase-invoices/", PurchaseInvoiceListCreateView.as_view(), name="purchase-invoice-list-create"),
]
