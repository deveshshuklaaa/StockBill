from rest_framework import serializers

from .models import InventoryBalance, Product, PurchaseInvoice, PurchaseLineItem, StockLedger, Supplier, Warehouse


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
    tax = serializers.DecimalField(source="tax.rate", read_only=True, max_digits=5, decimal_places=2, allow_null=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "base_unit",
            "category",
            "brand",
            "unit_type",
            "unit_conversion_factor",
            "default_price",
            "cost_price",
            "tax",
            "hsn_sac",
            "is_tax_applicable",
            "current_stock",
            "low_stock_threshold",
            "is_active",
            "supplier",
            "supplier_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "supplier_name"]


class ProductPublicSerializer(serializers.ModelSerializer):
    tax = serializers.DecimalField(source="tax.rate", read_only=True, max_digits=5, decimal_places=2, allow_null=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "base_unit",
            "category",
            "brand",
            "unit_type",
            "unit_conversion_factor",
            "default_price",
            "tax",
            "hsn_sac",
            "is_tax_applicable",
            "current_stock",
            "low_stock_threshold",
            "is_active",
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
            "quantity_delta",
            "reference_type",
            "reference_id",
            "unit_cost",
            "reason",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "product_name", "warehouse_name", "quantity_delta", "created_by"]


class InventoryBalanceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = InventoryBalance
        fields = ["id", "product", "product_name", "warehouse", "warehouse_name", "quantity_on_hand", "average_cost", "created_at", "updated_at"]
        read_only_fields = fields


class PurchaseLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseLineItem
        fields = ["id", "product", "product_name", "quantity", "unit_cost", "line_total"]
        read_only_fields = ["id", "product_name", "line_total"]


class PurchaseInvoiceSerializer(serializers.ModelSerializer):
    line_items = PurchaseLineItemSerializer(many=True, required=True)

    class Meta:
        model = PurchaseInvoice
        fields = ["id", "supplier", "warehouse", "invoice_number", "invoice_date", "total_amount", "created_by", "line_items", "created_at"]
        read_only_fields = ["id", "total_amount", "created_by", "created_at"]

    def create(self, validated_data):
        from .services import receive_purchase

        line_items = validated_data.pop("line_items")
        return receive_purchase(created_by=self.context["request"].user, line_items=line_items, **validated_data)
