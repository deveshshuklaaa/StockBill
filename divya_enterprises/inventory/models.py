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
    GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"

    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=10, blank=True)
    is_active = models.BooleanField(default=True)
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
    PURCHASE_REVERSAL = "PURCHASE_REVERSAL"
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
            PURCHASE_REVERSAL,
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
    STATE_DRAFT = "DRAFT"
    STATE_POSTED = "POSTED"
    STATE_CANCELLED = "CANCELLED"
    STATE_CHOICES = [
        (STATE_DRAFT, "Draft"),
        (STATE_POSTED, "Posted"),
        (STATE_CANCELLED, "Cancelled"),
    ]
    TAX_MODE_EXCLUSIVE = "exclusive"
    TAX_MODE_INCLUSIVE = "inclusive"
    TAX_MODE_CHOICES = [
        (TAX_MODE_EXCLUSIVE, "Exclusive"),
        (TAX_MODE_INCLUSIVE, "Inclusive"),
    ]

    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_invoices"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="purchase_invoices"
    )
    purchase_number = models.CharField(
        max_length=50, blank=True, null=True, unique=True
    )
    supplier_invoice_no = models.CharField(max_length=50, blank=True)
    invoice_date = models.DateField()
    state = models.CharField(max_length=12, choices=STATE_CHOICES, default=STATE_DRAFT)
    tax_mode = models.CharField(
        max_length=10, choices=TAX_MODE_CHOICES, default=TAX_MODE_EXCLUSIVE
    )
    supplier_name_snapshot = models.CharField(max_length=255, blank=True)
    supplier_gstin_snapshot = models.CharField(max_length=25, blank=True)
    supplier_state_snapshot = models.CharField(max_length=100, blank=True)
    supplier_state_code_snapshot = models.CharField(max_length=10, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    taxable_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igst_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_purchase_invoices",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_purchase_invoices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["supplier", "supplier_invoice_no"]),
            models.Index(fields=["state", "-invoice_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "supplier_invoice_no"],
                name="unique_supplier_invoice_no_per_supplier",
                condition=~models.Q(supplier_invoice_no=""),
            )
        ]

    def __str__(self):
        return self.purchase_number or f"Purchase draft #{self.pk}"    # Financial fields that must never change once inventory has moved.
    # cancelled_at/cancelled_by/cancellation_reason are set once by the
    # POSTED→CANCELLED transition and frozen afterwards by the state guard.
    IMMUTABLE_FIELDS = [
        "supplier_id",
        "warehouse_id",
        "purchase_number",
        "supplier_invoice_no",
        "invoice_date",
        "tax_mode",
        "supplier_name_snapshot",
        "supplier_gstin_snapshot",
        "supplier_state_snapshot",
        "supplier_state_code_snapshot",
        "subtotal",
        "discount_total",
        "taxable_total",
        "cgst_total",
        "sgst_total",
        "igst_total",
        "total_amount",
        "posted_at",
    ]

    def delete(self, *args, **kwargs):
        if self.state != self.STATE_DRAFT:
            raise ValueError("Only draft purchases can be deleted.")
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.only(
                "state", *type(self).IMMUTABLE_FIELDS
            ).get(pk=self.pk)
            if (
                self.state != stored.state
                and not getattr(self, "_allow_lifecycle_transition", False)
            ):
                raise ValueError(
                    "Purchase lifecycle transitions must use purchase services."
                )
            if stored.state in {self.STATE_POSTED, self.STATE_CANCELLED}:
                if any(
                    getattr(self, field) != getattr(stored, field)
                    for field in self.IMMUTABLE_FIELDS
                ):
                    raise ValueError(
                        "Posted and cancelled purchase financial fields are immutable."
                    )
        super().save(*args, **kwargs)


class PurchaseLineItem(models.Model):
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.CASCADE, related_name="line_items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_line_items"
    )
    product_name_snapshot = models.CharField(max_length=255, blank=True)
    sku_snapshot = models.CharField(max_length=64, blank=True)
    hsn_sac_snapshot = models.CharField(max_length=50, blank=True)
    base_unit_snapshot = models.CharField(max_length=20, blank=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)]
    )
    purchase_unit_name = models.CharField(max_length=50, default="piece")
    conversion_factor = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=1,
        validators=[MinValueValidator(0.001)],
    )
    base_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=0
    )
    rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_cost_snapshot = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)

    IMMUTABLE_FIELDS = [
        "purchase_invoice_id",
        "product_id",
        "product_name_snapshot",
        "sku_snapshot",
        "hsn_sac_snapshot",
        "base_unit_snapshot",
        "quantity",
        "purchase_unit_name",
        "conversion_factor",
        "base_quantity",
        "rate",
        "discount_amount",
        "tax_rate",
        "cgst_rate",
        "cgst_amount",
        "sgst_rate",
        "sgst_amount",
        "igst_rate",
        "igst_amount",
        "taxable_value",
        "line_total",
        "unit_cost_snapshot",
    ]

    def __str__(self):
        return f"{self.purchase_invoice} - {self.product_name_snapshot or self.product.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.get(pk=self.pk)
            if stored.purchase_invoice.state != PurchaseInvoice.STATE_DRAFT:
                if any(
                    getattr(self, field) != getattr(stored, field)
                    for field in self.IMMUTABLE_FIELDS
                ):
                    raise ValueError(
                        "Posted and cancelled purchase lines are immutable."
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.purchase_invoice.state != PurchaseInvoice.STATE_DRAFT:
            raise ValueError("Only draft purchase lines can be deleted.")
        return super().delete(*args, **kwargs)


class PurchaseNumberCounter(models.Model):
    """One row per financial year; serializes PI number assignment."""

    fy_code = models.CharField(max_length=10, unique=True)
    last_serial = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseIdempotencyKey(models.Model):
    key = models.CharField(max_length=255, unique=True)
    request_hash = models.CharField(max_length=64, default="")
    purchase = models.OneToOneField(
        PurchaseInvoice, on_delete=models.PROTECT, related_name="idempotency_record"
    )
    created_at = models.DateTimeField(auto_now_add=True)
