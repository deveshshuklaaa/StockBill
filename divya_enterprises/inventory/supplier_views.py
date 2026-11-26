"""API for damaged-goods returns to suppliers and their 1:1 replacements."""

from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Product, Supplier, SupplierReplacementReceipt, SupplierReturn, Warehouse
from .permissions import IsAdminOrReadOnly
from .supplier_return_services import receive_replacement, replaced_quantity, return_to_supplier


class SupplierReplacementReceiptSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)

    class Meta:
        model = SupplierReplacementReceipt
        fields = ["id", "warehouse", "warehouse_code", "quantity", "value", "receipt_date", "reference", "notes", "created_at"]
        read_only_fields = fields


class SupplierReturnSerializer(serializers.ModelSerializer):
    display_number = serializers.CharField(read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    replaced_quantity = serializers.SerializerMethodField()
    outstanding_quantity = serializers.SerializerMethodField()
    replacements = SupplierReplacementReceiptSerializer(many=True, read_only=True)

    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    # Optional: defaults to the Damaged / Quarantine warehouse.
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all(), required=False, allow_null=True)
    # Optional: defaults to the latest purchase cost from this supplier.
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    return_date = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = SupplierReturn
        fields = [
            "id", "display_number", "supplier", "supplier_name", "product", "product_name",
            "warehouse", "warehouse_code", "quantity", "unit_cost", "value", "return_date",
            "reference", "notes", "replaced_quantity", "outstanding_quantity", "replacements", "created_at",
        ]
        read_only_fields = ["id", "value", "created_at"]

    def get_replaced_quantity(self, obj):
        return replaced_quantity(obj)

    def get_outstanding_quantity(self, obj):
        return obj.quantity - replaced_quantity(obj)

    def create(self, validated_data):
        return return_to_supplier(created_by=self.context["request"].user, **validated_data)


class SupplierReturnListCreateView(generics.ListCreateAPIView):
    serializer_class = SupplierReturnSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = SupplierReturn.objects.select_related("supplier", "product", "warehouse").prefetch_related("replacements__warehouse")
        supplier = (self.request.query_params.get("supplier") or "").strip()
        if supplier:
            if not supplier.isdigit():
                raise ValidationError({"supplier": ["supplier must be a numeric id."]})
            queryset = queryset.filter(supplier_id=int(supplier))
        return queryset


class SupplierReturnDetailView(generics.RetrieveAPIView):
    queryset = SupplierReturn.objects.select_related("supplier", "product", "warehouse").prefetch_related("replacements__warehouse")
    serializer_class = SupplierReturnSerializer
    permission_classes = [permissions.IsAuthenticated]


class _ReplacementInputSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    # Optional: defaults to Main.
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all(), required=False, allow_null=True)
    receipt_date = serializers.DateField(required=False, allow_null=True)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class SupplierReplacementCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def post(self, request, pk):
        supplier_return = generics.get_object_or_404(SupplierReturn, pk=pk)
        data = _ReplacementInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        receive_replacement(supplier_return=supplier_return, created_by=request.user, **data.validated_data)
        supplier_return = SupplierReturn.objects.prefetch_related("replacements__warehouse").get(pk=pk)
        return Response(SupplierReturnSerializer(supplier_return).data, status=status.HTTP_201_CREATED)
