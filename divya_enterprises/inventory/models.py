from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    """Catalogue category used to drive dynamic product attributes."""

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AttributeDefinition(models.Model):
    """Strongly typed catalogue attribute; values stored per product in typed columns."""

    TYPE_TEXT = "TEXT"
    TYPE_INTEGER = "INTEGER"
    TYPE_DECIMAL = "DECIMAL"
    TYPE_BOOLEAN = "BOOLEAN"
    TYPE_CHOICE = "CHOICE"
    TYPE_DATE = "DATE"
    DATA_TYPE_CHOICES = [
        (TYPE_TEXT, "Text"),
        (TYPE_INTEGER, "Integer"),
        (TYPE_DECIMAL, "Decimal"),
        (TYPE_BOOLEAN, "Boolean"),
        (TYPE_CHOICE, "Choice"),
        (TYPE_DATE, "Date"),
    ]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    data_type = models.CharField(max_length=10, choices=DATA_TYPE_CHOICES)
    unit = models.CharField(
        max_length=20, blank=True, help_text="Presentation metadata, e.g. kg, ml, mm."
    )
    decimal_places = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.only("data_type").get(pk=self.pk)
            if (
                stored.data_type != self.data_type
                and ProductAttributeValue.objects.filter(
                    attribute_definition=self
                ).exists()
            ):
                raise ValueError(
                    "Attribute data_type is immutable once product values exist."
                )
        return super().save(*args, **kwargs)


class AttributeChoice(models.Model):
    """Allowed option for a CHOICE attribute; owned by the attribute definition."""

    attribute_definition = models.ForeignKey(
        AttributeDefinition, on_delete=models.CASCADE, related_name="choices"
    )
    value = models.CharField(max_length=100)
    label = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attribute_definition", "value"],
                name="unique_attribute_choice_value",
            )
        ]
        ordering = ["display_order", "value"]

    def __str__(self):
        return f"{self.attribute_definition.name}: {self.label}"


class CategoryAttribute(models.Model):
    """Assignment of an attribute to a category with per-category behaviour flags."""

    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="attribute_assignments"
    )
    attribute_definition = models.ForeignKey(
        AttributeDefinition,
        on_delete=models.CASCADE,
        related_name="category_assignments",
    )
    is_required = models.BooleanField(default=False)
    is_filterable = models.BooleanField(default=False)
    is_invoice_visible = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "attribute_definition"],
                name="unique_category_attribute",
            )
        ]
        ordering = ["display_order", "attribute_definition__name"]

    def __str__(self):
        return f"{self.category.name} → {self.attribute_definition.name}"


class ProductAttributeValue(models.Model):
    """Typed dynamic attribute value for a product; exactly one value_* column is populated."""

    product = models.ForeignKey(
        "Product", on_delete=models.CASCADE, related_name="attribute_values"
    )
    attribute_definition = models.ForeignKey(
        AttributeDefinition, on_delete=models.PROTECT, related_name="product_values"
    )
    value_text = models.TextField(blank=True, null=True)
    value_integer = models.BigIntegerField(null=True, blank=True)
    value_number = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    value_boolean = models.BooleanField(null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_choice = models.ForeignKey(
        AttributeChoice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="product_values",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "attribute_definition"],
                name="unique_product_attribute_value",
            )
        ]
        indexes = [
            models.Index(fields=["attribute_definition", "value_integer"]),
            models.Index(fields=["attribute_definition", "value_number"]),
            models.Index(fields=["attribute_definition", "value_text"]),
            models.Index(fields=["attribute_definition", "value_choice"]),
        ]

    def __str__(self):
        return f"{self.product.name}: {self.attribute_definition.code}"

    def typed_value(self):
        """Return the strongly typed Python value for this row."""
        data_type = self.attribute_definition.data_type
        if data_type == AttributeDefinition.TYPE_TEXT:
            return self.value_text
        if data_type == AttributeDefinition.TYPE_INTEGER:
            return self.value_integer
        if data_type == AttributeDefinition.TYPE_DECIMAL:
            return self.value_number
        if data_type == AttributeDefinition.TYPE_BOOLEAN:
            return self.value_boolean
        if data_type == AttributeDefinition.TYPE_DATE:
            return self.value_date
        if data_type == AttributeDefinition.TYPE_CHOICE:
            return self.value_choice.value if self.value_choice else None
        return None

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "Product attribute values cannot be edited in place; replace through the product API."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not getattr(self, "_allow_service_update", False):
            raise ValueError(
                "Product attribute values cannot be deleted directly; use the product API."
            )
        return super().delete(*args, **kwargs)


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name


class TaxRate(models.Model):
    name = models.CharField(max_length=50, unique=True)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class Product(models.Model):
    UNIT_CARTON = "carton"
    UNIT_BOX = "box"
    UNIT_PIECE = "piece"
    UNIT_CHOICES = [
        (UNIT_CARTON, "Carton"),
        (UNIT_BOX, "Box"),
        (UNIT_PIECE, "Piece"),
    ]

    name = models.CharField(max_length=255)
    base_unit = models.CharField(
        max_length=20, choices=UNIT_CHOICES, default=UNIT_PIECE
    )
    category = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    unit_type = models.CharField(
        max_length=20, choices=UNIT_CHOICES, default=UNIT_PIECE
    )
    unit_conversion_factor = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=1,
        validators=[MinValueValidator(0.001)],
    )
    sku = models.CharField(max_length=64, unique=True, null=True, blank=True)
    mrp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    default_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.ForeignKey(
        TaxRate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    hsn_sac = models.CharField(max_length=50, blank=True)
    is_tax_applicable = models.BooleanField(default=True)
    current_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    low_stock_threshold = models.DecimalField(
        max_digits=12, decimal_places=3, default=0
    )
    is_active = models.BooleanField(default=True)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    catalogue_category = models.ForeignKey(
        "Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["name", "category", "brand"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk is not None and not getattr(
            self, "_allow_stock_cache_update", False
        ):
            loaded_stock = getattr(self, "_loaded_current_stock", self.current_stock)
            if self.current_stock != loaded_stock:
                raise ValueError(
                    "Product stock is derived from inventory movements and cannot be edited directly."
                )
        return super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_current_stock = instance.current_stock
        return instance


class StockLedger(models.Model):
    OPENING_STOCK = "OPENING_STOCK"
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    SALE_REVERSAL = "SALE_REVERSAL"
    SALES_RETURN = "SALES_RETURN"
    PURCHASE_RETURN = "PURCHASE_RETURN"
    DAMAGE = "DAMAGE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    MOVEMENT_CHOICES = [
        (value, value.replace("_", " ").title())
        for value in [
            OPENING_STOCK,
            PURCHASE,
            SALE,
            SALE_REVERSAL,
            SALES_RETURN,
            PURCHASE_RETURN,
            DAMAGE,
            ADJUSTMENT,
            TRANSFER_IN,
            TRANSFER_OUT,
        ]
    ]
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_entries"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="stock_entries"
    )
    quantity_change = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(-999999999)]
    )
    quantity_delta = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    movement_type = models.CharField(
        max_length=20, choices=MOVEMENT_CHOICES, default=ADJUSTMENT
    )
    reference = models.CharField(max_length=255, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["product", "warehouse", "created_at"])]

    def __str__(self):
        return f"{self.product.name} {self.quantity_change} ({self.movement_type})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "Stock ledger entries are immutable; create a compensating movement."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Stock ledger entries cannot be deleted.")


class InventoryBalance(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="inventory_balances"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="inventory_balances"
    )
    quantity_on_hand = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(0)]
    )
    average_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse"], name="unique_product_warehouse_balance"
            )
        ]

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.code}: {self.quantity_on_hand}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not getattr(self, "_allow_service_update", False):
            raise ValueError(
                "Inventory balances may only change through inventory services."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Inventory balances cannot be deleted.")


class PurchaseInvoice(models.Model):
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_invoices"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="purchase_invoices"
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField()
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_purchase_invoices",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class PurchaseLineItem(models.Model):
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.CASCADE, related_name="line_items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_line_items"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)]
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
