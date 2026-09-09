from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from billing.models import AuditLog
from .attribute_services import get_category_schema
from .models import (
    AttributeChoice,
    AttributeDefinition,
    Category,
    CategoryAttribute,
    InventoryBalance,
    Product,
    PurchaseInvoice,
    StockLedger,
    Supplier,
    TaxRate,
    Warehouse,
)
from .permissions import IsAdminOrReadOnly
from .serializers import (
    AttributeChoiceSerializer,
    AttributeDefinitionSerializer,
    CategoryAttributeSerializer,
    CategorySerializer,
    InventoryBalanceSerializer,
    ProductPublicSerializer,
    ProductSerializer,
    PurchaseInvoiceSerializer,
    StockLedgerSerializer,
    SupplierSerializer,
    TaxRateSerializer,
    WarehouseSerializer,
)


def _audit(request, action, entity, entity_id):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        entity_type=entity,
        entity_id=entity_id,
    )


_INVALID = object()


def _typed_value_column(definition):
    """Map an AttributeDefinition data type to its ProductAttributeValue column."""
    mapping = {
        AttributeDefinition.TYPE_TEXT: "value_text",
        AttributeDefinition.TYPE_INTEGER: "value_integer",
        AttributeDefinition.TYPE_DECIMAL: "value_number",
        AttributeDefinition.TYPE_BOOLEAN: "value_boolean",
        AttributeDefinition.TYPE_DATE: "value_date",
        AttributeDefinition.TYPE_CHOICE: "value_choice__value",
    }
    return mapping.get(definition.data_type)


def _filter_typed_value(definition, raw):
    """Coerce a filter parameter to the attribute's type; _INVALID means unparseable."""
    from .models import AttributeChoice

    data_type = definition.data_type
    try:
        if data_type == AttributeDefinition.TYPE_TEXT:
            return str(raw).strip()
        if data_type == AttributeDefinition.TYPE_INTEGER:
            return int(str(raw).strip())
        if data_type == AttributeDefinition.TYPE_DECIMAL:
            return Decimal(str(raw).strip())
        if data_type == AttributeDefinition.TYPE_BOOLEAN:
            lowered = str(raw).strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            return _INVALID
        if data_type == AttributeDefinition.TYPE_DATE:
            return date.fromisoformat(str(raw).strip())
        if data_type == AttributeDefinition.TYPE_CHOICE:
            choice = AttributeChoice.objects.filter(
                attribute_definition=definition, value=str(raw).strip()
            ).first()
            if choice is None:
                return _INVALID
            # The filter matches on value_choice__value, so return the raw value string.
            return choice.value
    except (ValueError, TypeError, InvalidOperation):
        return _INVALID
    return _INVALID


class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_create(self, serializer):
        category = serializer.save()
        _audit(self.request, "category_created", "Category", category.pk)


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        category = serializer.save()
        if was_active and not category.is_active:
            _audit(self.request, "category_deactivated", "Category", category.pk)
        else:
            _audit(self.request, "category_updated", "Category", category.pk)

    def perform_destroy(self, instance):
        if instance.products.exists():
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {
                    "detail": "Category has products and cannot be deleted; deactivate it instead."
                }
            )
        _audit(self.request, "category_deleted", "Category", instance.pk)
        instance.delete()


class CategorySchemaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        category = generics.get_object_or_404(Category, pk=pk)
        return Response(get_category_schema(category))


class TaxRateListView(generics.ListAPIView):
    """Read-only tax configuration list used by product forms."""

    queryset = TaxRate.objects.filter(is_active=True).order_by("rate")
    serializer_class = TaxRateSerializer
    permission_classes = [permissions.IsAuthenticated]


class AttributeDefinitionListCreateView(generics.ListCreateAPIView):
    queryset = (
        AttributeDefinition.objects.prefetch_related("choices").all().order_by("name")
    )
    serializer_class = AttributeDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_create(self, serializer):
        definition = serializer.save()
        _audit(
            self.request,
            "attribute_definition_created",
            "AttributeDefinition",
            definition.pk,
        )


class AttributeDefinitionDetailView(generics.RetrieveUpdateAPIView):
    queryset = AttributeDefinition.objects.prefetch_related("choices").all()
    serializer_class = AttributeDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_update(self, serializer):
        definition = serializer.save()
        _audit(
            self.request,
            "attribute_definition_updated",
            "AttributeDefinition",
            definition.pk,
        )


class AttributeChoiceListCreateView(generics.ListCreateAPIView):
    """Manage allowed option values for CHOICE attributes."""

    serializer_class = AttributeChoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = AttributeChoice.objects.select_related("attribute_definition").all()
        attribute_id = self.request.query_params.get("attribute")
        if attribute_id:
            queryset = queryset.filter(attribute_definition_id=attribute_id)
        return queryset.order_by("attribute_definition__name", "display_order", "value")

    def perform_create(self, serializer):
        choice = serializer.save()
        _audit(
            self.request,
            "attribute_choice_created",
            "AttributeChoice",
            choice.pk,
        )


class AttributeChoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = AttributeChoice.objects.select_related("attribute_definition").all()
    serializer_class = AttributeChoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_update(self, serializer):
        choice = serializer.save()
        _audit(self.request, "attribute_choice_updated", "AttributeChoice", choice.pk)

    def perform_destroy(self, instance):
        _audit(self.request, "attribute_choice_deleted", "AttributeChoice", instance.pk)
        instance.delete()


class CategoryAttributeListCreateView(generics.ListCreateAPIView):
    serializer_class = CategoryAttributeSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        return (
            CategoryAttribute.objects.filter(category_id=self.kwargs["category_pk"])
            .select_related("category", "attribute_definition")
            .prefetch_related("attribute_definition__choices")
            .order_by("display_order", "attribute_definition__name")
        )

    def get_serializer(self, *args, **kwargs):
        # Inject the URL category so DRF's unique-together validator sees both fields.
        if isinstance(kwargs.get("data"), dict):
            kwargs["data"] = {**kwargs["data"], "category": self.kwargs["category_pk"]}
        return super().get_serializer(*args, **kwargs)

    def perform_create(self, serializer):
        assignment = serializer.save(category_id=self.kwargs["category_pk"])
        _audit(
            self.request,
            "category_attribute_assigned",
            "CategoryAttribute",
            assignment.pk,
        )


class CategoryAttributeDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CategoryAttributeSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        return (
            CategoryAttribute.objects.filter(category_id=self.kwargs["category_pk"])
            .select_related("category", "attribute_definition")
            .prefetch_related("attribute_definition__choices")
        )

    def perform_update(self, serializer):
        assignment = serializer.save()
        _audit(
            self.request,
            "category_attribute_updated",
            "CategoryAttribute",
            assignment.pk,
        )

    def perform_destroy(self, instance):
        _audit(
            self.request, "category_attribute_removed", "CategoryAttribute", instance.pk
        )
        instance.delete()


class ProductListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.request.user.normalized_role == User.ROLE_STAFF:
            return ProductPublicSerializer
        return ProductSerializer

    def get_queryset(self):
        queryset = (
            Product.objects.select_related("catalogue_category", "supplier", "tax")
            .prefetch_related(
                "attribute_values__attribute_definition",
                "attribute_values__value_choice",
            )
            .all()
            .order_by("name")
        )
        return self._apply_dynamic_filters(queryset)

    def _apply_dynamic_filters(self, queryset):
        """Support ?attr_<code>=<value> filters for attributes flagged filterable."""
        for key, raw in (self.request.query_params or {}).items():
            if not key.startswith("attr_") or raw in (None, ""):
                continue
            code = key[len("attr_") :]
            definition = AttributeDefinition.objects.filter(code=code).first()
            if definition is None:
                continue
            # Only categories that flag this attribute as filterable may be matched.
            allowed_categories = list(
                CategoryAttribute.objects.filter(
                    attribute_definition=definition, is_filterable=True
                ).values_list("category_id", flat=True)
            )
            if not allowed_categories:
                continue
            column = _typed_value_column(definition)
            value = _filter_typed_value(definition, raw)
            if column is None or value is _INVALID:
                continue
            queryset = queryset.filter(
                catalogue_category_id__in=allowed_categories,
                attribute_values__attribute_definition=definition,
                **{f"attribute_values__{column}": value},
            )
        return queryset


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = (
        Product.objects.select_related("catalogue_category", "supplier", "tax")
        .prefetch_related(
            "attribute_values__attribute_definition", "attribute_values__value_choice"
        )
        .all()
    )
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.request.user.normalized_role == User.ROLE_STAFF:
            return ProductPublicSerializer
        return ProductSerializer

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        _audit(self.request, "product_archived", "Product", instance.pk)


class SupplierListCreateView(generics.ListCreateAPIView):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def perform_create(self, serializer):
        supplier = serializer.save()
        _audit(self.request, "supplier_created", "Supplier", supplier.pk)


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


class StockLedgerListCreateView(generics.ListAPIView):
    queryset = (
        StockLedger.objects.select_related("product", "warehouse")
        .all()
        .order_by("-created_at")
    )
    serializer_class = StockLedgerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class StockLedgerDetailView(generics.RetrieveAPIView):
    queryset = StockLedger.objects.select_related("product", "warehouse").all()
    serializer_class = StockLedgerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class InventoryBalanceListView(generics.ListAPIView):
    queryset = (
        InventoryBalance.objects.select_related("product", "warehouse")
        .all()
        .order_by("warehouse__code", "product__name")
    )
    serializer_class = InventoryBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]


class PurchaseInvoiceListCreateView(generics.ListCreateAPIView):
    queryset = (
        PurchaseInvoice.objects.select_related("supplier", "warehouse", "created_by")
        .prefetch_related("line_items")
        .all()
        .order_by("-created_at")
    )
    serializer_class = PurchaseInvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
