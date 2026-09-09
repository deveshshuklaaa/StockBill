from rest_framework import serializers

from .attribute_services import (
    apply_product_attributes,
    assemble_product_attributes,
    validate_and_normalize_attributes,
)
from .models import (
    AttributeChoice,
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    PurchaseInvoice,
    PurchaseLineItem,
    StockLedger,
    Supplier,
    TaxRate,
    Warehouse,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "code",
            "name",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        fields = ["id", "name", "rate", "is_active"]


class AttributeChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeChoice
        fields = [
            "id",
            "attribute_definition",
            "value",
            "label",
            "display_order",
        ]
        read_only_fields = ["id"]


class AttributeDefinitionSerializer(serializers.ModelSerializer):
    choices = AttributeChoiceSerializer(many=True, read_only=True)

    class Meta:
        model = AttributeDefinition
        fields = [
            "id",
            "code",
            "name",
            "data_type",
            "unit",
            "decimal_places",
            "description",
            "is_active",
            "choices",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_decimal_places(self, value):
        if value is not None and value > 6:
            raise serializers.ValidationError("decimal_places cannot exceed 6.")
        return value

    def validate(self, attrs):
        data_type = attrs.get("data_type", getattr(self.instance, "data_type", None))
        if data_type == AttributeDefinition.TYPE_DECIMAL:
            if self.instance is None and attrs.get("decimal_places") is None:
                raise serializers.ValidationError(
                    {
                        "decimal_places": "decimal_places is required for DECIMAL attributes."
                    }
                )
        if (
            attrs.get("decimal_places") is not None
            and data_type != AttributeDefinition.TYPE_DECIMAL
        ):
            raise serializers.ValidationError(
                {"decimal_places": "decimal_places only applies to DECIMAL attributes."}
            )
        return attrs


class CategoryAttributeSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False
    )
    attribute_code = serializers.CharField(
        source="attribute_definition.code", read_only=True
    )
    attribute_name = serializers.CharField(
        source="attribute_definition.name", read_only=True
    )
    data_type = serializers.CharField(
        source="attribute_definition.data_type", read_only=True
    )
    unit = serializers.CharField(source="attribute_definition.unit", read_only=True)
    choices = serializers.SerializerMethodField()

    class Meta:
        model = CategoryAttribute
        fields = [
            "id",
            "category",
            "attribute_definition",
            "attribute_code",
            "attribute_name",
            "data_type",
            "unit",
            "is_required",
            "is_filterable",
            "is_invoice_visible",
            "display_order",
            "choices",
        ]
        read_only_fields = [
            "id",
            "attribute_code",
            "attribute_name",
            "data_type",
            "unit",
            "choices",
        ]

    def get_choices(self, obj):
        if obj.attribute_definition.data_type == AttributeDefinition.TYPE_CHOICE:
            return [
                {"value": c.value, "label": c.label}
                for c in obj.attribute_definition.choices.all()
            ]
        return []


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
    tax = serializers.PrimaryKeyRelatedField(
        queryset=TaxRate.objects.all(), allow_null=True, required=False
    )
    tax_rate = serializers.DecimalField(
        source="tax.rate",
        read_only=True,
        max_digits=5,
        decimal_places=2,
        allow_null=True,
    )
    catalogue_category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), allow_null=True, required=False
    )
    category_name = serializers.CharField(
        source="catalogue_category.name", read_only=True
    )
    attributes = serializers.DictField(
        child=serializers.JSONField(), required=False, write_only=True
    )

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
            "sku",
            "mrp",
            "default_price",
            "cost_price",
            "tax",
            "tax_rate",
            "hsn_sac",
            "is_tax_applicable",
            "current_stock",
            "low_stock_threshold",
            "is_active",
            "supplier",
            "supplier_name",
            "catalogue_category",
            "category_name",
            "attributes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "supplier_name",
            "tax_rate",
            "category_name",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["attributes"] = assemble_product_attributes(instance)
        return data

    def validate(self, attrs):
        category = attrs.get(
            "catalogue_category", getattr(self.instance, "catalogue_category", None)
        )
        if category is not None and not category.is_active:
            raise serializers.ValidationError(
                {
                    "catalogue_category": [
                        "Inactive categories cannot be assigned to products."
                    ]
                }
            )
        submitted = attrs.pop("attributes", None)
        partial = getattr(self, "partial", False)
        if submitted is not None:
            current = self.instance
            merged = submitted
            if partial and current is not None and category is not None:
                # PATCH merges: omitted attribute codes keep their stored values,
                # restricted to attributes assigned to the product's category.
                stored = assemble_product_attributes(current)
                assigned_codes = set(
                    CategoryAttribute.objects.filter(
                        category=category, attribute_definition__is_active=True
                    ).values_list("attribute_definition__code", flat=True)
                )
                merged = {
                    code: value
                    for code, value in {**stored, **submitted}.items()
                    if code in assigned_codes
                }
            self._validated_attributes = validate_and_normalize_attributes(
                category, merged, current_product=current
            )
            self._check_duplicate_variant(category)
        else:
            self._validated_attributes = None
        return attrs

    def _check_duplicate_variant(self, category):
        """Reject exact catalogue-variant duplicates: same name + same attribute values.

        Different weight/MRP variants stay separate rows; only a fully identical
        name + category + attribute set is treated as a duplicate.
        """
        name = self.initial_data.get("name")
        if not name:
            return
        incoming = {
            definition.code: typed for definition, typed in self._validated_attributes
        }
        candidates = Product.objects.filter(
            name__iexact=name, catalogue_category=category
        ).exclude(pk=getattr(self.instance, "pk", None))
        for candidate in candidates:
            candidate_values = assemble_product_attributes(candidate)
            if candidate_values == incoming:
                raise serializers.ValidationError(
                    {
                        "attributes": [
                            "A product with the same name and attribute values already exists."
                        ]
                    }
                )

    def create(self, validated_data):
        validated_attributes = getattr(self, "_validated_attributes", None) or []
        product = Product.objects.create(**validated_data)
        apply_product_attributes(product=product, validated=validated_attributes)
        return product

    def update(self, instance, validated_data):
        validated_attributes = getattr(self, "_validated_attributes", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if validated_attributes is not None:
            apply_product_attributes(product=instance, validated=validated_attributes)
        return instance


class ProductPublicSerializer(serializers.ModelSerializer):
    tax = serializers.DecimalField(
        source="tax.rate",
        read_only=True,
        max_digits=5,
        decimal_places=2,
        allow_null=True,
    )
    tax_rate = serializers.DecimalField(
        source="tax.rate",
        read_only=True,
        max_digits=5,
        decimal_places=2,
        allow_null=True,
    )
    catalogue_category = serializers.PrimaryKeyRelatedField(read_only=True)
    category_name = serializers.CharField(
        source="catalogue_category.name", read_only=True
    )
    attributes = serializers.SerializerMethodField()

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
            "sku",
            "mrp",
            "default_price",
            "tax",
            "tax_rate",
            "hsn_sac",
            "is_tax_applicable",
            "current_stock",
            "low_stock_threshold",
            "is_active",
            "supplier",
            "catalogue_category",
            "category_name",
            "attributes",
        ]
        read_only_fields = fields

    def get_attributes(self, obj):
        return assemble_product_attributes(obj)


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
        read_only_fields = [
            "id",
            "created_at",
            "product_name",
            "warehouse_name",
            "quantity_delta",
            "created_by",
        ]


class InventoryBalanceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = InventoryBalance
        fields = [
            "id",
            "product",
            "product_name",
            "warehouse",
            "warehouse_name",
            "quantity_on_hand",
            "average_cost",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PurchaseLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseLineItem
        fields = [
            "id",
            "product",
            "product_name",
            "quantity",
            "unit_cost",
            "line_total",
        ]
        read_only_fields = ["id", "product_name", "line_total"]


class PurchaseInvoiceSerializer(serializers.ModelSerializer):
    line_items = PurchaseLineItemSerializer(many=True, required=True)

    class Meta:
        model = PurchaseInvoice
        fields = [
            "id",
            "supplier",
            "warehouse",
            "invoice_number",
            "invoice_date",
            "total_amount",
            "created_by",
            "line_items",
            "created_at",
        ]
        read_only_fields = ["id", "total_amount", "created_by", "created_at"]

    def create(self, validated_data):
        from .services import receive_purchase

        line_items = validated_data.pop("line_items")
        return receive_purchase(
            created_by=self.context["request"].user,
            line_items=line_items,
            **validated_data,
        )
