from datetime import date
from decimal import Decimal

from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsAdminUser, IsStaffUser
from inventory.models import Product

from .models import CreditNoteLineItem, Invoice, InvoiceLineItem, Payment


MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)
QUANTITY_FIELD = DecimalField(max_digits=18, decimal_places=3)


def _parse_date(value, parameter, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{parameter} must use YYYY-MM-DD format.")


def _credit_note_total_subquery(field_name):
    return Subquery(
        CreditNoteLineItem.objects.filter(invoice_line_item=OuterRef("pk"))
        .values("invoice_line_item")
        .annotate(total=Sum(field_name))
        .values("total")[:1],
        output_field=QUANTITY_FIELD if field_name == "quantity" else MONEY_FIELD,
    )


class DailySalesReportView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            report_date = _parse_date(request.query_params.get("date"), "date", date.today())
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        invoices = Invoice.objects.filter(invoice_date=report_date)
        tax_totals = (
            InvoiceLineItem.objects.filter(invoice__invoice_date=report_date)
            .values("tax_rate")
            .annotate(total=Coalesce(Sum("tax_amount"), Value(Decimal("0.00")), output_field=MONEY_FIELD))
            .order_by("tax_rate")
        )
        totals = invoices.aggregate(
            total=Count("id"),
            cash_count=Count("id", filter=Q(payment_type=Invoice.PAYMENT_TYPE_CASH)),
            credit_count=Count("id", filter=Q(payment_type=Invoice.PAYMENT_TYPE_CREDIT)),
            sold_cash=Coalesce(
                Sum("total_amount", filter=Q(payment_type=Invoice.PAYMENT_TYPE_CASH)),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
            sold_credit=Coalesce(
                Sum("total_amount", filter=Q(payment_type=Invoice.PAYMENT_TYPE_CREDIT)),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
            revenue=Coalesce(Sum("total_amount"), Value(Decimal("0.00")), output_field=MONEY_FIELD),
        )
        cash_collected = Payment.objects.filter(payment_date=report_date).aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00")), output_field=MONEY_FIELD)
        )["total"]
        return Response(
            {
                "date": report_date,
                "invoice_count": totals["total"],
                "invoice_count_by_payment_type": {"cash": totals["cash_count"], "credit": totals["credit_count"]},
                "sold_cash_today": totals["sold_cash"],
                "sold_on_credit_today": totals["sold_credit"],
                "cash_collected_today": cash_collected,
                "total_revenue": totals["revenue"],
                "tax_collected_by_slab": {
                    format(row["tax_rate"].normalize(), "f").rstrip("0").rstrip(".") or "0": row["total"]
                    for row in tax_totals
                },
            }
        )


class StockValuationReportView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        products = Product.objects.annotate(
            cost_value=ExpressionWrapper(F("current_stock") * F("cost_price"), output_field=MONEY_FIELD),
            selling_value=ExpressionWrapper(F("current_stock") * F("default_price"), output_field=MONEY_FIELD),
        ).order_by("name")
        totals = products.aggregate(
            cost_value=Coalesce(
                Sum(ExpressionWrapper(F("current_stock") * F("cost_price"), output_field=MONEY_FIELD)),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
            selling_value=Coalesce(
                Sum(ExpressionWrapper(F("current_stock") * F("default_price"), output_field=MONEY_FIELD)),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
        )
        is_admin = request.user.normalized_role == User.ROLE_ADMIN
        rows = []
        for product in products:
            row = {
                "product_id": product.id,
                "product_name": product.name,
                "current_stock": product.current_stock,
                "stock_value_selling_price": product.selling_value,
            }
            if is_admin:
                row["stock_value_cost_price"] = product.cost_value
            rows.append(row)
        response = {"products": rows, "total_valuation_selling_price": totals["selling_value"]}
        if is_admin:
            response["total_valuation_cost_price"] = totals["cost_value"]
        return Response(response)


class ProfitLossReportView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date = _parse_date(request.query_params.get("from"), "from")
            to_date = _parse_date(request.query_params.get("to"), "to")
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        if from_date is None or to_date is None:
            return Response({"detail": "Both from and to dates are required."}, status=status.HTTP_400_BAD_REQUEST)
        if from_date > to_date:
            return Response({"detail": "from must be on or before to."}, status=status.HTTP_400_BAD_REQUEST)

        line_items = InvoiceLineItem.objects.filter(
            invoice__invoice_date__range=(from_date, to_date)
        ).annotate(
            reversed_quantity=Coalesce(_credit_note_total_subquery("quantity"), Value(Decimal("0.00")), output_field=QUANTITY_FIELD),
            reversed_revenue=Coalesce(_credit_note_total_subquery("line_total"), Value(Decimal("0.00")), output_field=MONEY_FIELD),
        ).annotate(
            effective_quantity=ExpressionWrapper(F("quantity") - F("reversed_quantity"), output_field=QUANTITY_FIELD),
            effective_revenue=ExpressionWrapper(F("line_total") - F("reversed_revenue"), output_field=MONEY_FIELD),
            current_cogs=ExpressionWrapper(
                F("cogs_amount") - F("reversed_quantity") * F("cost_price_snapshot"),
                output_field=MONEY_FIELD,
            ),
        )
        totals = line_items.aggregate(
            revenue=Coalesce(Sum("effective_revenue"), Value(Decimal("0.00")), output_field=MONEY_FIELD),
            cogs=Coalesce(Sum("current_cogs"), Value(Decimal("0.00")), output_field=MONEY_FIELD),
        )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "cost_price_assumption": "COGS uses each product's current cost_price; historical cost snapshots are not tracked.",
                "revenue": totals["revenue"],
                "cost_of_goods_sold": totals["cogs"],
                "net_profit": totals["revenue"] - totals["cogs"],
            }
        )


class TopProductsReportView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date = _parse_date(request.query_params.get("from"), "from")
            to_date = _parse_date(request.query_params.get("to"), "to")
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        if from_date is None or to_date is None:
            return Response({"detail": "Both from and to dates are required."}, status=status.HTTP_400_BAD_REQUEST)
        if from_date > to_date:
            return Response({"detail": "from must be on or before to."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get("limit", "10"))
        except ValueError:
            return Response({"detail": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        sort_by = request.query_params.get("sort_by", "quantity")
        if sort_by not in {"quantity", "revenue"} or limit < 1:
            return Response({"detail": "sort_by must be quantity or revenue, and limit must be positive."}, status=status.HTTP_400_BAD_REQUEST)

        line_items = InvoiceLineItem.objects.filter(invoice__invoice_date__range=(from_date, to_date)).annotate(
            reversed_quantity=Coalesce(_credit_note_total_subquery("quantity"), Value(Decimal("0.00")), output_field=QUANTITY_FIELD),
            reversed_revenue=Coalesce(_credit_note_total_subquery("line_total"), Value(Decimal("0.00")), output_field=MONEY_FIELD),
        ).annotate(
            effective_quantity=ExpressionWrapper(F("quantity") - F("reversed_quantity"), output_field=QUANTITY_FIELD),
            effective_revenue=ExpressionWrapper(F("line_total") - F("reversed_revenue"), output_field=MONEY_FIELD),
        )
        ranking = "-total_revenue" if sort_by == "revenue" else "-total_quantity"
        products = (
            line_items.values("product_id", "product__name")
            .annotate(
                total_quantity=Sum("effective_quantity"),
                total_revenue=Sum("effective_revenue"),
            )
            .filter(total_quantity__gt=0)
            .order_by(ranking, "product__name")[:limit]
        )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "sort_by": sort_by,
                "products": [
                    {
                        "product_id": row["product_id"],
                        "product_name": row["product__name"],
                        "total_quantity": row["total_quantity"],
                        "total_revenue": row["total_revenue"],
                    }
                    for row in products
                ],
            }
        )
