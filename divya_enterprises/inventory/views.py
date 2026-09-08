from rest_framework import generics, permissions

from .models import InventoryBalance, Product, PurchaseInvoice, StockLedger, Supplier, Warehouse
from .permissions import CanManageInventory, IsAdminOrReadOnly
from .serializers import (
    ProductPublicSerializer,
    ProductSerializer,
    StockLedgerSerializer,
    SupplierSerializer,
    WarehouseSerializer,
    InventoryBalanceSerializer,
    PurchaseInvoiceSerializer,
)


class SupplierListCreateView(generics.ListCreateAPIView):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class SupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class WarehouseListCreateView(generics.ListCreateAPIView):
    queryset = Warehouse.objects.all().order_by("name")
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class WarehouseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class ProductListCreateView(generics.ListCreateAPIView):
    queryset = Product.objects.all().order_by("name")
    permission_classes = [permissions.IsAuthenticated, CanManageInventory]

    def get_serializer_class(self):
        if self.request.user.role == "staff":
            return ProductPublicSerializer
        return ProductSerializer


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated, CanManageInventory]

    def get_serializer_class(self):
        if self.request.user.role == "staff":
            return ProductPublicSerializer
        return ProductSerializer

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class StockLedgerListCreateView(generics.ListCreateAPIView):
    queryset = StockLedger.objects.select_related("product", "warehouse").all().order_by("-created_at")
    serializer_class = StockLedgerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class StockLedgerDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StockLedger.objects.select_related("product", "warehouse").all()
    serializer_class = StockLedgerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class InventoryBalanceListView(generics.ListAPIView):
    queryset = InventoryBalance.objects.select_related("product", "warehouse").all().order_by("warehouse__code", "product__name")
    serializer_class = InventoryBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]


class PurchaseInvoiceListCreateView(generics.ListCreateAPIView):
    queryset = PurchaseInvoice.objects.select_related("supplier", "warehouse", "created_by").prefetch_related("line_items").all().order_by("-created_at")
    serializer_class = PurchaseInvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
