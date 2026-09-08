from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "contact_info",
            "billing_address",
            "shipping_address",
            "state",
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
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
