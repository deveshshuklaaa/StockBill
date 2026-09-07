from rest_framework import serializers

from .models import CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem, Payment


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    tax_rate = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = InvoiceLineItem
        fields = [
            "id",
            "invoice",
            "product",
            "product_name",
            "quantity",
            "rate_charged",
            "tax_rate",
            "tax_amount",
            "line_total",
            "created_at",
        ]
        read_only_fields = ["id", "invoice", "created_at", "product_name", "tax_amount", "line_total"]


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    line_items = InvoiceLineItemSerializer(many=True, required=True)
    payment_status = serializers.ReadOnlyField(source="computed_payment_status")
    payment_type = serializers.ChoiceField(choices=["cash", "credit"], write_only=True, default="credit")

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "customer",
            "customer_name",
            "invoice_date",
            "payment_type",
            "payment_status",
            "total_amount",
            "notes",
            "created_by",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer_name", "invoice_date", "payment_type", "created_at", "updated_at", "payment_status", "created_by", "total_amount"]

    def validate(self, attrs):
        payment_type = attrs.get("payment_type", "credit")
        if payment_type == "credit" and attrs.get("customer") is None:
            raise serializers.ValidationError({"customer": "A registered customer is required for credit invoices."})
        if not attrs.get("line_items"):
            raise serializers.ValidationError({"line_items": "At least one line item is required."})
        return attrs

    def create(self, validated_data):
        from .services import create_invoice

        payment_type = validated_data.pop("payment_type", "credit")
        line_items = validated_data.pop("line_items")
        return create_invoice(
            created_by=self.context["request"].user,
            payment_type=payment_type,
            line_items=line_items,
            **validated_data,
        )


class CreditNoteLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = CreditNoteLineItem
        fields = [
            "id",
            "credit_note",
            "invoice_line_item",
            "product",
            "product_name",
            "quantity",
            "rate_charged",
            "tax_rate",
            "tax_amount",
            "line_total",
            "created_at",
        ]
        read_only_fields = ["id", "credit_note", "created_at", "product_name", "tax_amount", "line_total", "rate_charged", "tax_rate"]


class CreditNoteSerializer(serializers.ModelSerializer):
    original_invoice_number = serializers.CharField(source="original_invoice.invoice_number", read_only=True)
    line_items = CreditNoteLineItemSerializer(many=True, required=True)

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "original_invoice",
            "original_invoice_number",
            "reason",
            "note_date",
            "total_amount",
            "created_by",
            "line_items",
            "created_at",
        ]
        read_only_fields = ["id", "original_invoice_number", "note_date", "created_at", "total_amount", "created_by"]

    def validate(self, attrs):
        if not attrs.get("line_items"):
            raise serializers.ValidationError({"line_items": "At least one reversal line item is required."})
        return attrs

    def create(self, validated_data):
        from .services import create_credit_note

        line_items = validated_data.pop("line_items")
        return create_credit_note(
            created_by=self.context["request"].user,
            line_items=line_items,
            **validated_data,
        )


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "customer",
            "customer_name",
            "invoice",
            "invoice_number",
            "amount",
            "payment_date",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "customer_name", "invoice_number", "payment_date", "created_at"]
