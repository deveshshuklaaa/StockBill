from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


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


class Product(models.Model):
    TAX_5 = 5
    TAX_18 = 18
    TAX_40 = 40
    TAX_CHOICES = [
        (TAX_5, "5%"),
        (TAX_18, "18%"),
        (TAX_40, "40%"),
    ]

    UNIT_CARTON = "carton"
    UNIT_BOX = "box"
    UNIT_PIECE = "piece"
    UNIT_CHOICES = [
        (UNIT_CARTON, "Carton"),
        (UNIT_BOX, "Box"),
        (UNIT_PIECE, "Piece"),
    ]

    name = models.CharField(max_length=255)
    base_unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default=UNIT_PIECE)
    category = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    unit_type = models.CharField(max_length=20, choices=UNIT_CHOICES, default=UNIT_PIECE)
    unit_conversion_factor = models.DecimalField(max_digits=12, decimal_places=3, default=1, validators=[MinValueValidator(0.001)])
    default_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_slab = models.PositiveIntegerField(choices=TAX_CHOICES, default=TAX_18)
    current_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["name", "category", "brand"]) ]

    def __str__(self):
        return self.name


class StockLedger(models.Model):
    OPENING_STOCK = "OPENING_STOCK"
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    SALES_RETURN = "SALES_RETURN"
    PURCHASE_RETURN = "PURCHASE_RETURN"
    DAMAGE = "DAMAGE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    MOVEMENT_CHOICES = [(value, value.replace("_", " ").title()) for value in [
        OPENING_STOCK, PURCHASE, SALE, SALES_RETURN, PURCHASE_RETURN,
        DAMAGE, ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT,
    ]]
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_entries")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_entries")
    quantity_change = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(-999999999)])
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES, default=ADJUSTMENT)
    reference = models.CharField(max_length=255, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["product", "warehouse", "created_at"])]

    def __str__(self):
        return f"{self.product.name} {self.quantity_change} ({self.movement_type})"


class InventoryBalance(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="inventory_balances")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="inventory_balances")
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    average_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "warehouse"], name="unique_product_warehouse_balance")]

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.code}: {self.quantity_on_hand}"


class PurchaseInvoice(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_invoices")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchase_invoices")
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField()
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_purchase_invoices")
    created_at = models.DateTimeField(auto_now_add=True)


class PurchaseLineItem(models.Model):
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name="line_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchase_line_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
