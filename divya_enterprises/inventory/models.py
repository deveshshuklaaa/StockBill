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
    category = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    unit_type = models.CharField(max_length=20, choices=UNIT_CHOICES, default=UNIT_PIECE)
    unit_conversion_factor = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    default_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_slab = models.PositiveIntegerField(choices=TAX_CHOICES, default=TAX_18)
    current_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["name", "category", "brand"]) ]

    def __str__(self):
        return self.name


class StockLedger(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_entries")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_entries")
    quantity_change = models.DecimalField(max_digits=12, decimal_places=3)
    movement_type = models.CharField(max_length=20, choices=[("in", "In"), ("out", "Out")], default="in")
    reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} {self.quantity_change} ({self.movement_type})"
