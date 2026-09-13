from rest_framework import serializers

from .models import Customer


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
