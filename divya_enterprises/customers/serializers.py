from rest_framework import serializers

from .models import Customer, CustomerMRPPricing


class CustomerSerializer(serializers.ModelSerializer):
    outstanding_balance = serializers.SerializerMethodField()
    available_credit = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "contact_info",
            "billing_address",
            "shipping_address",
            "state",
            "state_code",
            "pincode",
            "customer_type",
            "gst_registration_type",
            "gstin",
            "credit_limit",
            "credit_days",
            "opening_balance",
            "is_regular",
            "is_active",
            "created_at",
            "updated_at",
            "outstanding_balance",
            "available_credit",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "outstanding_balance", "available_credit"]

    def get_outstanding_balance(self, obj):
        return obj.outstanding_balance

    def get_available_credit(self, obj):
        return obj.available_credit


class CustomerMRPPricingSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerMRPPricing
        fields = [
            "id",
            "customer",
            "customer_name",
            "mrp",
            "rate_per_piece",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer_name", "created_at", "updated_at"]

    def validate_mrp(self, value):
        from decimal import Decimal
        if value is None or Decimal(str(value)) <= Decimal("0.00"):
            raise serializers.ValidationError("MRP must be greater than 0.")
        return value

    def validate_rate_per_piece(self, value):
        from decimal import Decimal
        if value is None or Decimal(str(value)) < Decimal("0.00"):
            raise serializers.ValidationError("Rate per piece cannot be negative.")
        return value

    def validate(self, attrs):
        customer = attrs.get("customer") or getattr(self.instance, "customer", None)
        mrp = attrs.get("mrp") or getattr(self.instance, "mrp", None)
        if customer and mrp is not None:
            qs = CustomerMRPPricing.objects.filter(customer=customer, mrp=mrp)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"mrp": [f"Pricing for MRP ₹{mrp} already exists for this customer."]}
                )
        return attrs
