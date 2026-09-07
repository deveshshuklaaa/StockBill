from rest_framework import serializers

from .models import CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem, Payment


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

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
        read_only_fields = ["id", "created_at", "product_name", "tax_amount", "line_total"]


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    payment_status = serializers.ReadOnlyField(source="computed_payment_status")

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "customer",
            "customer_name",
            "invoice_date",
            "payment_status",
            "total_amount",
            "notes",
            "created_by",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer_name", "invoice_date", "created_at", "updated_at", "line_items", "payment_status"]


class CreditNoteLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = CreditNoteLineItem
        fields = [
            "id",
            "credit_note",
            "product",
            "product_name",
            "quantity",
            "rate_charged",
            "tax_rate",
            "tax_amount",
            "line_total",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "product_name", "tax_amount", "line_total"]


class CreditNoteSerializer(serializers.ModelSerializer):
    original_invoice_number = serializers.CharField(source="original_invoice.invoice_number", read_only=True)
    line_items = CreditNoteLineItemSerializer(many=True, read_only=True)

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
        read_only_fields = ["id", "original_invoice_number", "note_date", "created_at", "line_items"]


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
