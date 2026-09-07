from rest_framework import serializers

from .models import Product, StockLedger, Supplier, Warehouse


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_info", "created_at"]
        read_only_fields = ["id", "created_at"]


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "name", "code", "address"]
        read_only_fields = ["id"]


class ProductSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "category",
            "brand",
            "unit_type",
            "unit_conversion_factor",
            "default_price",
            "cost_price",
            "tax_slab",
            "current_stock",
            "low_stock_threshold",
            "supplier",
            "supplier_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "supplier_name"]


class ProductPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "category",
            "brand",
            "unit_type",
            "unit_conversion_factor",
            "default_price",
            "tax_slab",
            "current_stock",
            "low_stock_threshold",
            "supplier",
        ]
        read_only_fields = fields


class StockLedgerSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockLedger
        fields = [
            "id",
            "product",
            "product_name",
            "warehouse",
            "warehouse_name",
            "quantity_change",
            "movement_type",
            "reference",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "product_name", "warehouse_name"]
