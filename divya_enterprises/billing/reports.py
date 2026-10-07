"""Management reports for Divya Enterprises.

Report definitions (authoritative, tested):

SALES SUMMARY — /api/reports/sales/
  Basis: POSTED invoices only. DRAFT and CANCELLED excluded from active
  sales; cancelled count reported separately. Date basis is
  Invoice.invoice_date (the posting date, auto-set at creation).
  Reconciles with /invoices?state=POSTED for the same period.
  gross_sales = Σ invoice line gross (qty × rate) from line snapshots
  discounts     = Σ line discount_amount
  taxable_sales = Σ line taxable_value_snapshot
  gst           = Σ (cgst+sgst+igst) line amounts
  net_sales     = Σ invoice.total_amount (= taxable + gst)
  cogs          = Σ line cogs_amount (historical snapshot at posting)
  gross_profit  = taxable_sales − cogs (tax-exclusive operating profit)

PURCHASE SUMMARY — /api/reports/purchases/
  Basis: POSTED PurchaseInvoice only, using header totals snapshotted at
  posting (never current cost/WAC). Date basis is invoice_date (business
  date on the bill). Reconciles with /purchases state=POSTED.
  Supplier breakdown aggregates the same rows by supplier.

INVENTORY VALUATION — /api/reports/inventory/
  Value = Σ InventoryBalance.quantity_on_hand × average_cost (the WAC the
  inventory service maintains) + legacy fallback current_stock × cost_price
  only for products with no balance rows. Reconciles with
  /warehouses/summary/ total_value for the same filters.

STOCK MOVEMENT — /api/reports/stock-movement/
  Direct read-only view over the append-only StockLedger with the same
  filters as the stock-ledger list plus per-page totals computed server-side
  over the WHOLE filtered set (never just the loaded page).

PRODUCT SALES — /api/reports/products/
  POSTED invoice line items grouped by product, date range required.
  Uses historical snapshots: taxable_value_snapshot, tax amounts,
  cogs_amount, cost_price_snapshot. Current product cost/WAC is NEVER
  read. Variant = product_name_snapshot.
  gross_profit = taxable_sales_revenue − taxable_cogs.

CUSTOMER SALES — /api/reports/customers/
  POSTED invoices grouped by customer (walk-in = customer null, identified
  by the customer_name_snapshot "Walk-in customer" semantics), date range
  optional. Outstanding comes from Customer.outstanding_balance — the same
  authoritative property the customer UI uses.

TAX SUMMARY — /api/reports/tax/
  OUTPUT tax: POSTED invoice line cgst/sgst/igst snapshots.
  INPUT tax: POSTED purchase line cgst/sgst/igst snapshots.
  Historical snapshots only; never current TaxRate rows. Internal summary,
  not a GST return.

PROFIT — /api/reports/profit/
  POSTED lines only. revenue = Σ effective_taxable_revenue (tax-exclusive),
  cogs = Σ effective_cogs (historical snapshots), gross_profit = revenue − cogs.
  Credit notes reduce revenue and COGS proportionally.
  Per-product and per-customer breakdowns aggregate the same terms.

TOP PRODUCTS — /api/reports/top-products/
  POSTED lines only, ranked by quantity / taxable revenue / gross profit (historical
  snapshots). Date range required.

DASHBOARD — /api/reports/dashboard/
  Every number comes from the same queries above (today's posted sales and
  purchases, inventory valuation total, customer outstanding, active
  counts, low stock by low_stock_threshold, period gross profit).

All endpoints are read-only GET with IsAuthenticated; financial reports
(profit, tax, dashboard financial section, customer sales) additionally
require admin via IsAdminUser, matching existing report policy.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminUser, IsStaffUser
from customers.models import Customer
from inventory.models import (
    InventoryBalance,
    Product,
    PurchaseInvoice,
    PurchaseLineItem,
    StockLedger,
    Supplier,
)

from .models import BusinessProfile, CreditNoteLineItem, Invoice, InvoiceLineItem, Payment
from .tax_engine import round_inr

MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)
QUANTITY_FIELD = DecimalField(max_digits=18, decimal_places=3)
ZERO_MONEY = Decimal("0.00")
ZERO_QTY = Decimal("0.000")

VALID_SORTS = {"quantity", "revenue", "profit"}


def _parse_date(value, parameter, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{parameter} must use YYYY-MM-DD format.")


def _date_range(request, *, required=False, default_days=30):
    """Parse from/to; from is inclusive start of day, to is inclusive end of day.

    DateField comparisons (__gte/__lte) are calendar-day inclusive on both
    ends, so from=X&to=X covers the complete single day X.
    """
    try:
        from_date = _parse_date(request.query_params.get("from"), "from")
        to_date = _parse_date(request.query_params.get("to"), "to")
    except ValueError as error:
        raise ValueError(str(error))
    if required and (from_date is None or to_date is None):
        raise ValueError("Both from and to dates are required.")
    if from_date is None:
        from_date = date.today() - timedelta(days=default_days)
    if to_date is None:
        to_date = date.today()
    if from_date > to_date:
        raise ValueError("from must be on or before to.")
    return from_date, to_date


def _bad_request(message):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _credit_note_total_subquery(field_name):
    """Credit-note reversal totals for an invoice line, as a subquery.

    Used instead of annotation chaining: Sum() cannot wrap an annotated
    aggregate inside .values() groups, so reversal totals per line are
    computed via Subquery — same pattern as the original reporting module.
    """
    from django.db.models import OuterRef, Subquery

    return Subquery(
        CreditNoteLineItem.objects.filter(invoice_line_item=OuterRef("pk"))
        .values("invoice_line_item")
        .annotate(total=Sum(field_name))
        .values("total")[:1],
        output_field=QUANTITY_FIELD if field_name == "quantity" else MONEY_FIELD,
    )


def _credit_note_taxable_subquery():
    """Credit-note reversed taxable sales revenue (line_total - tax_amount) as a subquery."""
    from django.db.models import ExpressionWrapper, F, OuterRef, Subquery

    return Subquery(
        CreditNoteLineItem.objects.filter(invoice_line_item=OuterRef("pk"))
        .values("invoice_line_item")
        .annotate(
            total=Sum(
                ExpressionWrapper(
                    F("line_total") - F("tax_amount"),
                    output_field=MONEY_FIELD,
                )
            )
        )
        .values("total")[:1],
        output_field=MONEY_FIELD,
    )


def _posted_invoice_lines(from_date, to_date, customer=None, payment_type=None):
    """POSTED invoice lines in the inclusive date window.

    DRAFT lines are unposted promises and CANCELLED lines are reversed
    sales; neither is active revenue, so both are excluded from every
    sales figure in this module. Line snapshots (taxable_value_snapshot,
    tax amounts, cogs_amount) are the historical truth.
    """
    queryset = InvoiceLineItem.objects.filter(
        invoice__state=Invoice.STATE_POSTED,
        invoice__invoice_date__gte=from_date,
        invoice__invoice_date__lte=to_date,
    )
    if customer is not None:
        queryset = queryset.filter(invoice__customer=customer)
    if payment_type:
        queryset = queryset.filter(invoice__payment_type=payment_type)
    return queryset


class SalesSummaryReportView(APIView):
    """POSTED sales totals for a period; reconciles with Invoice History."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, default_days=0)
            customer = self._customer(request)
            payment_type = self._payment_type(request)
        except ValueError as error:
            return _bad_request(str(error))

        lines = _posted_invoice_lines(from_date, to_date, customer, payment_type)
        totals = lines.aggregate(
            gross_sales=Coalesce(
                Sum(ExpressionWrapper(F("quantity") * F("rate_charged"), output_field=MONEY_FIELD)),
                Value(ZERO_MONEY), output_field=MONEY_FIELD,
            ),
            discounts=Coalesce(Sum("discount_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            taxable_sales=Coalesce(Sum("taxable_value_snapshot"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cgst=Coalesce(Sum("cgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            sgst=Coalesce(Sum("sgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            igst=Coalesce(Sum("igst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            net_sales=Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cogs=Coalesce(Sum("cogs_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )

        invoices = Invoice.objects.filter(
            state=Invoice.STATE_POSTED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        if customer is not None:
            invoices = invoices.filter(customer=customer)
        if payment_type:
            invoices = invoices.filter(payment_type=payment_type)
        invoice_counts = invoices.aggregate(
            posted=Count("id"),
            cancelled=Count("id", filter=Q(state=Invoice.STATE_CANCELLED)),
        )
        cancelled_in_period = Invoice.objects.filter(
            state=Invoice.STATE_CANCELLED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        if customer is not None:
            cancelled_in_period = cancelled_in_period.filter(customer=customer)
        cancelled_count = cancelled_in_period.count()
        cancelled_value = cancelled_in_period.aggregate(
            total=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD)
        )["total"]

        gst = (totals["cgst"] or ZERO_MONEY) + (totals["sgst"] or ZERO_MONEY) + (totals["igst"] or ZERO_MONEY)
        net_sales = totals["net_sales"] or ZERO_MONEY
        taxable_sales = totals["taxable_sales"] or ZERO_MONEY
        cogs = totals["cogs"] or ZERO_MONEY
        gross_profit = taxable_sales - cogs
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED invoices only; DRAFT and CANCELLED excluded from active sales.",
                "invoice_count": invoice_counts["posted"],
                "cancelled_invoice_count": cancelled_count,
                "cancelled_invoice_value": cancelled_value,
                "gross_sales": totals["gross_sales"],
                "discounts": totals["discounts"],
                "taxable_sales": taxable_sales,
                "taxable_sales_revenue": taxable_sales,
                "gst": gst,
                "sales_gst": gst,
                "cgst": totals["cgst"],
                "sgst": totals["sgst"],
                "igst": totals["igst"],
                "net_sales": net_sales,
                "cogs": cogs,
                "taxable_cogs": cogs,
                "gross_profit": gross_profit,
            }
        )

    @staticmethod
    def _customer(request):
        raw = (request.query_params.get("customer") or "").strip()
        if not raw:
            return None
        if not raw.isdigit():
            raise ValueError("customer must be a numeric id.")
        customer = Customer.objects.filter(pk=int(raw)).first()
        if customer is None:
            raise ValueError("customer does not exist.")
        return customer

    @staticmethod
    def _payment_type(request):
        raw = (request.query_params.get("payment_type") or "").strip()
        if not raw:
            return None
        if raw not in {choice[0] for choice in Invoice.PAYMENT_TYPE_CHOICES}:
            raise ValueError("payment_type must be cash or credit.")
        return raw


class PurchaseSummaryReportView(APIView):
    """POSTED purchase totals using posting-time header snapshots."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, default_days=0)
            supplier = self._supplier(request)
        except ValueError as error:
            return _bad_request(str(error))

        purchases = PurchaseInvoice.objects.filter(
            state=PurchaseInvoice.STATE_POSTED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        if supplier is not None:
            purchases = purchases.filter(supplier=supplier)
        totals = purchases.aggregate(
            count=Count("id"),
            taxable=Coalesce(Sum("taxable_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cgst=Coalesce(Sum("cgst_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            sgst=Coalesce(Sum("sgst_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            igst=Coalesce(Sum("igst_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            total=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        cancelled = PurchaseInvoice.objects.filter(
            state=PurchaseInvoice.STATE_CANCELLED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        if supplier is not None:
            cancelled = cancelled.filter(supplier=supplier)
        cancelled_count = cancelled.count()
        cancelled_value = cancelled.aggregate(
            total=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD)
        )["total"]

        # Supplier-wise breakdown from the same filtered rows.
        by_supplier = list(
            purchases.select_related("supplier")
            .values(
                "supplier_id",
                "supplier__name",
                "supplier_name_snapshot",
            )
            .annotate(
                invoice_count=Count("id"),
                taxable_total=Coalesce(Sum("taxable_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
                gst_total=Coalesce(
                    Sum(ExpressionWrapper(F("cgst_total") + F("sgst_total") + F("igst_total"), output_field=MONEY_FIELD)),
                    Value(ZERO_MONEY), output_field=MONEY_FIELD,
                ),
                purchase_total=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .order_by("-purchase_total")
        )

        gst = (totals["cgst"] or ZERO_MONEY) + (totals["sgst"] or ZERO_MONEY) + (totals["igst"] or ZERO_MONEY)
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED purchases only, valued at posting-time header snapshots; CANCELLED excluded from active totals.",
                "purchase_count": totals["count"],
                "cancelled_purchase_count": cancelled_count,
                "cancelled_purchase_value": cancelled_value,
                "taxable_purchases": totals["taxable"],
                "gst": gst,
                "cgst": totals["cgst"],
                "sgst": totals["sgst"],
                "igst": totals["igst"],
                "total_purchase_value": totals["total"],
                "by_supplier": [
                    {
                        "supplier_id": row["supplier_id"],
                        "supplier_name": row["supplier__name"],
                        "supplier_name_snapshot": row["supplier_name_snapshot"],
                        "invoice_count": row["invoice_count"],
                        "taxable_total": row["taxable_total"],
                        "gst_total": row["gst_total"],
                        "purchase_total": row["purchase_total"],
                    }
                    for row in by_supplier
                ],
            }
        )

    @staticmethod
    def _supplier(request):
        raw = (request.query_params.get("supplier") or "").strip()
        if not raw:
            return None
        if not raw.isdigit():
            raise ValueError("supplier must be a numeric id.")
        supplier = Supplier.objects.filter(pk=int(raw)).first()
        if supplier is None:
            raise ValueError("supplier does not exist.")
        return supplier


def _inventory_valuation_rows(warehouse=None, category=None, is_active=None, search=""):
    """Valuation rows: quantity_on_hand × average_cost per balance.

    The authoritative value is InventoryBalance; the legacy
    current_stock × cost_price fallback only applies to products that have
    never been through any receipt (no balance rows), matching the
    semantics of the existing stock-valuation report.
    """
    balances = (
        InventoryBalance.objects.select_related("product", "warehouse", "product__catalogue_category")
        .filter(quantity_on_hand__gt=0)
    )
    if warehouse is not None:
        balances = balances.filter(warehouse=warehouse)
    if category is not None:
        balances = balances.filter(product__catalogue_category=category)
    if is_active is not None:
        balances = balances.filter(product__is_active=is_active)
    if search:
        balances = balances.filter(
            Q(product__name__icontains=search) | Q(product__sku__icontains=search)
        )
    return balances


class InventoryValuationReportView(APIView):
    """Inventory value = Σ quantity_on_hand × average_cost (WAC)."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        params = request.query_params or {}
        try:
            from inventory.models import Category, Warehouse

            warehouse_id = (params.get("warehouse") or "").strip()
            warehouse = None
            if warehouse_id:
                if not warehouse_id.isdigit():
                    return _bad_request("warehouse must be a numeric id.")
                warehouse = Warehouse.objects.filter(pk=int(warehouse_id)).first()
                if warehouse is None:
                    return _bad_request("warehouse does not exist.")
            category_id = (params.get("category") or "").strip()
            category = None
            if category_id:
                if not category_id.isdigit():
                    return _bad_request("category must be a numeric id.")
                category = Category.objects.filter(pk=int(category_id)).first()
                if category is None:
                    return _bad_request("category does not exist.")
        except ValueError:
            return _bad_request("Invalid filter.")
        active_param = (params.get("is_active") or "").strip().lower()
        is_active = None
        if active_param:
            if active_param not in {"true", "false"}:
                return _bad_request("is_active must be 'true' or 'false'.")
            is_active = active_param == "true"
        search = (params.get("search") or "").strip()

        balances = _inventory_valuation_rows(warehouse, category, is_active, search)
        value_expr = ExpressionWrapper(
            F("quantity_on_hand") * F("average_cost"), output_field=MONEY_FIELD
        )
        totals = balances.aggregate(
            product_count=Count("product", distinct=True),
            balance_count=Count("id"),
            quantity=Coalesce(Sum("quantity_on_hand"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
            value=Coalesce(Sum(value_expr), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )

        # Legacy fallback: products with stock but no balance rows at all.
        legacy_products = Product.objects.filter(is_active=True).exclude(
            inventory_balances__isnull=False
        )
        legacy_rows = []
        legacy_value = ZERO_MONEY
        legacy_quantity = ZERO_QTY
        if not warehouse and not category:
            # Only meaningful without warehouse/category scoping (legacy
            # current_stock is a global cache, not per-warehouse).
            for product in legacy_products:
                if is_active is not None and product.is_active != is_active:
                    continue
                if search and search.lower() not in product.name.lower() and search.lower() not in (product.sku or "").lower():
                    continue
                if product.current_stock and product.current_stock > 0:
                    legacy_rows.append(product)
                    legacy_quantity += product.current_stock
                    legacy_value += product.current_stock * product.cost_price

        by_warehouse = list(
            balances.values("warehouse_id", "warehouse__name", "warehouse__code")
            .annotate(
                product_count=Count("product", distinct=True),
                quantity=Coalesce(Sum("quantity_on_hand"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
                value=Coalesce(Sum(value_expr), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .order_by("warehouse__code")
        )

        return Response(
            {
                "rules": "Value = InventoryBalance.quantity_on_hand × average_cost (WAC). Legacy products without balances fall back to current_stock × cost_price.",
                "product_count": (totals["product_count"] or 0) + len(legacy_rows),
                "quantity_on_hand": (totals["quantity"] or ZERO_QTY) + legacy_quantity,
                "total_value": (totals["value"] or ZERO_MONEY) + legacy_value,
                "by_warehouse": [
                    {
                        "warehouse_id": row["warehouse_id"],
                        "warehouse_name": row["warehouse__name"],
                        "warehouse_code": row["warehouse__code"],
                        "product_count": row["product_count"],
                        "quantity": row["quantity"],
                        "value": row["value"],
                    }
                    for row in by_warehouse
                ],
            }
        )


class StockMovementReportView(APIView):
    """Read-only aggregate view over the append-only StockLedger."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        params = request.query_params or {}
        queryset = StockLedger.objects.select_related("product", "warehouse").all()
        try:
            product_id = (params.get("product") or "").strip()
            if product_id:
                if not product_id.isdigit():
                    return _bad_request("product must be a numeric id.")
                queryset = queryset.filter(product_id=int(product_id))
            warehouse_id = (params.get("warehouse") or "").strip()
            if warehouse_id:
                if not warehouse_id.isdigit():
                    return _bad_request("warehouse must be a numeric id.")
                queryset = queryset.filter(warehouse_id=int(warehouse_id))
            movement_type = (params.get("movement_type") or "").strip()
            if movement_type:
                valid = {choice[0] for choice in StockLedger.MOVEMENT_CHOICES}
                if movement_type not in valid:
                    return _bad_request(
                        f"movement_type must be one of: {', '.join(sorted(valid))}."
                    )
                queryset = queryset.filter(movement_type=movement_type)
            from_date = _parse_date(params.get("from"), "from")
            to_date = _parse_date(params.get("to"), "to")
            if from_date:
                queryset = queryset.filter(created_at__date__gte=from_date)
            if to_date:
                queryset = queryset.filter(created_at__date__lte=to_date)
            reference = (params.get("reference") or "").strip()
            if reference:
                queryset = queryset.filter(reference__icontains=reference)
        except ValueError as error:
            return _bad_request(str(error))

        # Server-side totals across the ENTIRE filtered set (not just a page).
        totals = queryset.aggregate(
            movement_count=Count("id"),
            net_quantity=Coalesce(Sum("quantity_change"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
            inflow=Coalesce(
                Sum("quantity_change", filter=Q(quantity_change__gt=0)),
                Value(ZERO_QTY), output_field=QUANTITY_FIELD,
            ),
            outflow=Coalesce(
                Sum("quantity_change", filter=Q(quantity_change__lt=0)),
                Value(ZERO_QTY), output_field=QUANTITY_FIELD,
            ),
        )
        by_movement = list(
            queryset.values("movement_type")
            .annotate(
                movement_count=Count("id"),
                net_quantity=Coalesce(Sum("quantity_change"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
            )
            .order_by("movement_type")
        )
        return Response(
            {
                "rules": "Append-only StockLedger; created_at (transaction timestamp) is the report time basis.",
                **totals,
                "by_movement_type": [
                    {
                        "movement_type": row["movement_type"],
                        "movement_count": row["movement_count"],
                        "net_quantity": row["net_quantity"],
                    }
                    for row in by_movement
                ],
            }
        )


class ProductSalesReportView(APIView):
    """Per-product sales from POSTED invoice line snapshots."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        lines = _posted_invoice_lines(from_date, to_date)
        rows = (
            lines.values(
                "product_id",
                "product__name",
                "product_name_snapshot",
                "base_unit_snapshot",
            )
            .annotate(
                quantity_sold=Coalesce(Sum("base_quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
                gross_sales=Coalesce(
                    Sum(ExpressionWrapper(F("quantity") * F("rate_charged"), output_field=MONEY_FIELD)),
                    Value(ZERO_MONEY), output_field=MONEY_FIELD,
                ),
                discounts=Coalesce(Sum("discount_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
                taxable_sales=Coalesce(Sum("taxable_value_snapshot"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
                gst=Coalesce(
                    Sum(ExpressionWrapper(F("cgst_amount") + F("sgst_amount") + F("igst_amount"), output_field=MONEY_FIELD)),
                    Value(ZERO_MONEY), output_field=MONEY_FIELD,
                ),
                sales_value=Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
                cogs=Coalesce(Sum("cogs_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .order_by("-taxable_sales", "product__name")
        )
        products = []
        total_cogs = ZERO_MONEY
        total_taxable_revenue = ZERO_MONEY
        total_sales_value = ZERO_MONEY
        for row in rows:
            taxable_revenue = row["taxable_sales"] or ZERO_MONEY
            cogs = row["cogs"] or ZERO_MONEY
            profit = taxable_revenue - cogs
            total_cogs += cogs
            total_taxable_revenue += taxable_revenue
            total_sales_value += (row["sales_value"] or ZERO_MONEY)
            products.append(
                {
                    "product_id": row["product_id"],
                    "product_name": row["product__name"],
                    "variant_snapshot": row["product_name_snapshot"],
                    "base_unit": row["base_unit_snapshot"],
                    "quantity_sold": row["quantity_sold"],
                    "gross_sales": row["gross_sales"],
                    "discounts": row["discounts"],
                    "taxable_sales": taxable_revenue,
                    "taxable_sales_revenue": taxable_revenue,
                    "gst": row["gst"],
                    "sales_gst": row["gst"],
                    "sales_value": row["sales_value"],
                    "cogs": cogs,
                    "taxable_cogs": cogs,
                    "gross_profit": profit,
                    "margin_percent": (
                        (profit / taxable_revenue * Decimal("100")).quantize(Decimal("0.1"))
                        if taxable_revenue > 0
                        else None
                    ),
                }
            )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED lines only; taxable_sales_revenue is tax-exclusive revenue; COGS is the historical cogs_amount snapshot; gross_profit = taxable_sales_revenue − cogs.",
                "products": products,
                "total_revenue": total_taxable_revenue,
                "total_taxable_sales": total_taxable_revenue,
                "total_sales_value": total_sales_value,
                "total_cogs": total_cogs,
                "total_taxable_cogs": total_cogs,
                "total_gross_profit": total_taxable_revenue - total_cogs,
            }
        )


class CustomerSalesReportView(APIView):
    """Per-customer sales; outstanding reused from the customer model."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, default_days=0)
        except ValueError as error:
            return _bad_request(str(error))

        invoices = Invoice.objects.filter(
            state=Invoice.STATE_POSTED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        rows = (
            invoices.values("customer_id", "customer__name", "customer_name_snapshot")
            .annotate(
                invoice_count=Count("id"),
                sales_value=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .order_by("-sales_value")
        )
        by_customer = []
        for row in rows:
            customer = None
            if row["customer_id"]:
                customer = Customer.objects.filter(pk=row["customer_id"]).first()
            by_customer.append(
                {
                    "customer_id": row["customer_id"],
                    "customer_name": row["customer__name"] or row["customer_name_snapshot"] or "Walk-in customer",
                    "is_walk_in": row["customer_id"] is None,
                    "invoice_count": row["invoice_count"],
                    "sales_value": row["sales_value"],
                    "outstanding_balance": (
                        customer.outstanding_balance if customer else None
                    ),
                }
            )
        totals = invoices.aggregate(
            invoice_count=Count("id"),
            sales_value=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        # Payments against these invoices (payment_date basis) for context.
        payments = Payment.objects.filter(
            payment_date__gte=from_date,
            payment_date__lte=to_date,
        ).aggregate(
            payment_count=Count("id"),
            payment_amount=Coalesce(Sum("amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED invoices only; outstanding is the customer model's authoritative balance (all-time, not period).",
                "invoice_count": totals["invoice_count"],
                "total_sales": totals["sales_value"],
                "payment_count": payments["payment_count"],
                "payment_amount": payments["payment_amount"],
                "by_customer": by_customer,
            }
        )


class TaxSummaryReportView(APIView):
    """Output GST from POSTED invoice lines; input GST from POSTED purchase lines.

    Internal summary only — not a government GST return.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        invoice_lines = InvoiceLineItem.objects.filter(
            invoice__state=Invoice.STATE_POSTED,
            invoice__invoice_date__gte=from_date,
            invoice__invoice_date__lte=to_date,
        )
        output = invoice_lines.aggregate(
            taxable=Coalesce(Sum("taxable_value_snapshot"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cgst=Coalesce(Sum("cgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            sgst=Coalesce(Sum("sgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            igst=Coalesce(Sum("igst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        purchase_lines = PurchaseLineItem.objects.filter(
            purchase_invoice__state=PurchaseInvoice.STATE_POSTED,
            purchase_invoice__invoice_date__gte=from_date,
            purchase_invoice__invoice_date__lte=to_date,
        )
        input_tax = purchase_lines.aggregate(
            taxable=Coalesce(Sum("taxable_value"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cgst=Coalesce(Sum("cgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            sgst=Coalesce(Sum("sgst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            igst=Coalesce(Sum("igst_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        output_total = (output["cgst"] or ZERO_MONEY) + (output["sgst"] or ZERO_MONEY) + (output["igst"] or ZERO_MONEY)
        input_total = (input_tax["cgst"] or ZERO_MONEY) + (input_tax["sgst"] or ZERO_MONEY) + (input_tax["igst"] or ZERO_MONEY)
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "Historical line tax snapshots only (never current TaxRate rows). Internal summary, not a GST return.",
                "output_tax": {
                    "taxable_sales": output["taxable"],
                    "cgst": output["cgst"],
                    "sgst": output["sgst"],
                    "igst": output["igst"],
                    "total": output_total,
                },
                "input_tax": {
                    "taxable_purchases": input_tax["taxable"],
                    "cgst": input_tax["cgst"],
                    "sgst": input_tax["sgst"],
                    "igst": input_tax["igst"],
                    "total": input_total,
                },
                "net_tax": output_total - input_total,
            }
        )


def get_profit_report_data(from_date, to_date):
    """Authoritative Gross Profit data across POSTED invoice lines.

    Accounting basis (Indian GST / standard trading margin):
    - Tax-exclusive Sales Revenue: pre-tax taxable amount from POSTED invoice lines,
      net of discounts and net of credit-note reversals.
      Output GST collected from customers is a statutory liability, never revenue.
    - Tax-exclusive COGS: historical cost of goods sold (base_quantity * WAC at posting),
      net of credit-note returns.
      Input GST paid on purchases is an ITC asset, excluded from WAC/inventory cost.
    - Gross Profit: Taxable Sales Revenue - Taxable COGS.
    """
    lines = (
        _posted_invoice_lines(from_date, to_date)
        .annotate(
            reversed_quantity=Coalesce(
                _credit_note_total_subquery("quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD
            ),
            reversed_taxable=Coalesce(
                _credit_note_taxable_subquery(), Value(ZERO_MONEY), output_field=MONEY_FIELD
            ),
            reversed_cogs=Coalesce(
                _credit_note_total_subquery("quantity") * F("cost_price_snapshot"),
                Value(ZERO_MONEY), output_field=MONEY_FIELD,
            ),
            reversed_tax=Coalesce(
                _credit_note_total_subquery("tax_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD
            ),
            reversed_line_total=Coalesce(
                _credit_note_total_subquery("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD
            ),
        )
        .annotate(
            effective_taxable_revenue=ExpressionWrapper(
                F("taxable_value_snapshot") - F("reversed_taxable"), output_field=MONEY_FIELD
            ),
            effective_cogs=ExpressionWrapper(
                F("cogs_amount") - F("reversed_cogs"), output_field=MONEY_FIELD
            ),
            effective_tax_amount=ExpressionWrapper(
                F("tax_amount") - F("reversed_tax"), output_field=MONEY_FIELD
            ),
            effective_total_value=ExpressionWrapper(
                F("line_total") - F("reversed_line_total"), output_field=MONEY_FIELD
            ),
        )
    )
    totals = lines.aggregate(
        taxable_sales_revenue=Coalesce(Sum("effective_taxable_revenue"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        taxable_cogs=Coalesce(Sum("effective_cogs"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        sales_gst=Coalesce(Sum("effective_tax_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        total_sales_value=Coalesce(Sum("effective_total_value"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
    )
    taxable_sales_revenue = totals["taxable_sales_revenue"] or ZERO_MONEY
    taxable_cogs = totals["taxable_cogs"] or ZERO_MONEY
    sales_gst = totals["sales_gst"] or ZERO_MONEY
    total_sales_value = totals["total_sales_value"] or ZERO_MONEY
    gross_profit = taxable_sales_revenue - taxable_cogs
    gross_margin_percent = (
        (gross_profit / taxable_sales_revenue * Decimal("100")).quantize(Decimal("0.1"))
        if taxable_sales_revenue > 0
        else None
    )

    by_product_rows = list(
        lines.values("product_id", "product__name")
        .annotate(
            taxable_sales_revenue=Coalesce(Sum("effective_taxable_revenue"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            taxable_cogs=Coalesce(Sum("effective_cogs"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        .order_by("-taxable_sales_revenue", "product__name")
    )
    by_product = [
        {
            "product_id": row["product_id"],
            "product_name": row["product__name"],
            "revenue": row["taxable_sales_revenue"],
            "taxable_sales_revenue": row["taxable_sales_revenue"],
            "cogs": row["taxable_cogs"],
            "taxable_cogs": row["taxable_cogs"],
            "gross_profit": (row["taxable_sales_revenue"] or ZERO_MONEY) - (row["taxable_cogs"] or ZERO_MONEY),
        }
        for row in by_product_rows
    ]

    return {
        "from": from_date,
        "to": to_date,
        "rules": (
            "POSTED lines only. Revenue = taxable_sales_revenue (tax-exclusive), "
            "COGS = historical cogs_amount snapshot (tax-exclusive). "
            "Gross profit = taxable_sales_revenue − taxable_cogs. Credit notes reduce both proportionally."
        ),
        "revenue": taxable_sales_revenue,
        "taxable_sales_revenue": taxable_sales_revenue,
        "cogs": taxable_cogs,
        "taxable_cogs": taxable_cogs,
        "gross_profit": gross_profit,
        "gross_margin_percent": gross_margin_percent,
        "sales_gst": sales_gst,
        "total_sales_value": total_sales_value,
        "by_product": by_product,
    }


class ProfitReportView(APIView):
    """Gross profit = POSTED taxable revenue − historical COGS snapshots."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        return Response(get_profit_report_data(from_date, to_date))


class TopProductsReportView(APIView):
    """POSTED-lines ranking by quantity, revenue, or gross profit."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
            limit = int(request.query_params.get("limit", "10"))
        except ValueError as error:
            return _bad_request(str(error))
        sort_by = (request.query_params.get("sort_by") or "quantity").strip()
        if sort_by not in VALID_SORTS or limit < 1:
            return _bad_request(
                "sort_by must be quantity, revenue, or profit; limit must be positive."
            )

        lines = _posted_invoice_lines(from_date, to_date)
        ranking = {
            "quantity": "-total_quantity",
            "revenue": "-total_revenue",
            "profit": "-total_profit",
        }[sort_by]
        annotate = {
            "total_quantity": Coalesce(Sum("base_quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
            "total_revenue": Coalesce(Sum("taxable_value_snapshot"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            "total_sales_value": Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            "total_cogs": Coalesce(Sum("cogs_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        }
        products = (
            lines.values("product_id", "product__name", "product_name_snapshot")
            .annotate(**annotate)
            .annotate(
                total_profit=ExpressionWrapper(
                    F("total_revenue") - F("total_cogs"), output_field=MONEY_FIELD
                )
            )
            .filter(total_quantity__gt=0)
            .order_by(ranking, "product__name")[:limit]
        )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "sort_by": sort_by,
                "rules": "POSTED lines only; historical line snapshots; current inventory is never a sales proxy.",
                "products": [
                    {
                        "product_id": row["product_id"],
                        "product_name": row["product__name"],
                        "variant_snapshot": row["product_name_snapshot"],
                        "rank": index + 1,
                        "total_quantity": row["total_quantity"],
                        "total_revenue": row["total_revenue"],
                        "total_cogs": row["total_cogs"],
                        "total_profit": row["total_profit"],
                    }
                    for index, row in enumerate(products)
                ],
            }
        )


class DashboardReportView(APIView):
    """Management overview; every number comes from the report queries above.

    Today's sales/purchases use the POSTED-only, invoice_date basis; the
    inventory value is the same InventoryBalance valuation as the
    inventory report; outstanding sums the customer model's authoritative
    property; gross profit uses historical COGS for the requested period.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, default_days=0)
        except ValueError as error:
            return _bad_request(str(error))
        today = date.today()

        sales_lines = _posted_invoice_lines(today, today)
        sales = sales_lines.aggregate(
            invoice_count=Count("invoice", distinct=True),
            net_sales=Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        purchase_today = PurchaseInvoice.objects.filter(
            state=PurchaseInvoice.STATE_POSTED, invoice_date=today
        ).aggregate(
            purchase_count=Count("id"),
            total=Coalesce(Sum("total_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )

        value_expr = ExpressionWrapper(
            F("quantity_on_hand") * F("average_cost"), output_field=MONEY_FIELD
        )
        inventory = InventoryBalance.objects.filter(quantity_on_hand__gt=0).aggregate(
            product_count=Count("product", distinct=True),
            total_value=Coalesce(Sum(value_expr), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )

        period_profit = get_profit_report_data(from_date, to_date)

        outstanding_total = ZERO_MONEY
        for customer in Customer.objects.filter(is_active=True):
            outstanding_total += customer.outstanding_balance

        active_customers = Customer.objects.filter(is_active=True).count()
        active_suppliers = Supplier.objects.filter(is_active=True).count()

        # Low stock: current_stock at or below the configured threshold.
        low_stock = list(
            Product.objects.filter(is_active=True)
            .filter(low_stock_threshold__gt=0)
            .filter(current_stock__lte=F("low_stock_threshold"))
            .order_by("current_stock")
            .values("id", "name", "current_stock", "low_stock_threshold")[:10]
        )

        recent_sales = list(
            Invoice.objects.filter(state=Invoice.STATE_POSTED)
            .order_by("-invoice_date", "-id")
            .values("id", "invoice_number", "invoice_date", "total_amount", "customer_name_snapshot")[:5]
        )
        recent_purchases = list(
            PurchaseInvoice.objects.filter(state=PurchaseInvoice.STATE_POSTED)
            .order_by("-invoice_date", "-id")
            .values("id", "purchase_number", "invoice_date", "total_amount", "supplier_name_snapshot")[:5]
        )

        top_products = (
            _posted_invoice_lines(from_date, to_date)
            .values("product_id", "product__name")
            .annotate(
                total_quantity=Coalesce(Sum("base_quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
                total_revenue=Coalesce(Sum("taxable_value_snapshot"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .filter(total_quantity__gt=0)
            .order_by("-total_revenue")[:5]
        )

        return Response(
            {
                "from": from_date,
                "to": to_date,
                "today": {
                    "invoice_count": sales["invoice_count"],
                    "net_sales": sales["net_sales"],
                    "purchase_count": purchase_today["purchase_count"],
                    "purchase_value": purchase_today["total"],
                },
                "inventory": {
                    "product_count": inventory["product_count"],
                    "total_value": inventory["total_value"],
                },
                "customer_outstanding_total": outstanding_total,
                "active_customers": active_customers,
                "active_suppliers": active_suppliers,
                "period": {
                    "revenue": period_profit["taxable_sales_revenue"],
                    "taxable_sales_revenue": period_profit["taxable_sales_revenue"],
                    "cogs": period_profit["taxable_cogs"],
                    "taxable_cogs": period_profit["taxable_cogs"],
                    "gross_profit": period_profit["gross_profit"],
                    "gross_margin_percent": period_profit["gross_margin_percent"],
                },
                "low_stock": low_stock,
                "recent_sales": recent_sales,
                "recent_purchases": recent_purchases,
                "top_products": list(top_products),
            }
        )


def get_sales_gst_report_data(from_date, to_date):
    """Authoritative invoice-level Sales GST Report data for POSTED invoices."""
    invoices = (
        Invoice.objects.filter(
            state=Invoice.STATE_POSTED,
            invoice_date__gte=from_date,
            invoice_date__lte=to_date,
        )
        .annotate(
            taxable_sum=Coalesce(
                Sum("line_items__taxable_value_snapshot"),
                Value(ZERO_MONEY),
                output_field=MONEY_FIELD,
            ),
            tax_sum=Coalesce(
                Sum("line_items__tax_amount"),
                Value(ZERO_MONEY),
                output_field=MONEY_FIELD,
            ),
            sgst_sum=Coalesce(
                Sum("line_items__sgst_amount"),
                Value(ZERO_MONEY),
                output_field=MONEY_FIELD,
            ),
            cgst_sum=Coalesce(
                Sum("line_items__cgst_amount"),
                Value(ZERO_MONEY),
                output_field=MONEY_FIELD,
            ),
            igst_sum=Coalesce(
                Sum("line_items__igst_amount"),
                Value(ZERO_MONEY),
                output_field=MONEY_FIELD,
            ),
        )
        .order_by("invoice_date", "invoice_number")
    )

    ZERO = Decimal("0.00")
    rows = []
    tot_bill_amt = ZERO
    tot_taxable = ZERO
    tot_tax = ZERO
    tot_sgst = ZERO
    tot_cgst = ZERO
    tot_igst = ZERO
    tot_total_gst = ZERO
    tot_r_off = ZERO

    # Pre-fetch authoritative line HSN snapshots
    invoice_ids = [inv.id for inv in invoices]
    hsn_map = defaultdict(list)
    if invoice_ids:
        line_hsns = (
            InvoiceLineItem.objects.filter(invoice_id__in=invoice_ids)
            .exclude(hsn_sac_snapshot="")
            .values_list("invoice_id", "hsn_sac_snapshot")
            .distinct()
        )
        for inv_id, hsn_val in line_hsns:
            cleaned = str(hsn_val).strip()
            if cleaned:
                hsn_map[inv_id].append(cleaned)

    for inv in invoices:
        display_bill_amt = round_inr(inv.total_amount).quantize(Decimal("0.01"))
        taxable = (inv.taxable_sum or ZERO).quantize(Decimal("0.01"))
        tax = (inv.tax_sum or ZERO).quantize(Decimal("0.01"))
        sgst = (inv.sgst_sum or ZERO).quantize(Decimal("0.01"))
        cgst = (inv.cgst_sum or ZERO).quantize(Decimal("0.01"))
        igst = (inv.igst_sum or ZERO).quantize(Decimal("0.01"))
        total_gst = (sgst + cgst + igst).quantize(Decimal("0.01"))
        sur = ZERO
        tax_free = ZERO
        exempted = ZERO
        r_off = (display_bill_amt - (taxable + tax)).quantize(Decimal("0.01"))

        tot_bill_amt += display_bill_amt
        tot_taxable += taxable
        tot_tax += tax
        tot_sgst += sgst
        tot_cgst += cgst
        tot_igst += igst
        tot_total_gst += total_gst
        tot_r_off += r_off

        raw_hsns = hsn_map.get(inv.id, [])
        unique_hsns = sorted(set(raw_hsns))
        hsn_str = ", ".join(unique_hsns)

        rows.append({
            "date": inv.invoice_date.strftime("%d-%m-%Y"),
            "bill_no": inv.invoice_number,
            "party_name": inv.customer_name_snapshot or "Walk-in customer",
            "gstin": inv.customer_gstin_snapshot or "",
            "hsn": hsn_str,
            "bill_amt": f"{display_bill_amt:.2f}",
            "taxable": f"{taxable:.2f}",
            "tax": f"{tax:.2f}",
            "sgst": f"{sgst:.2f}",
            "cgst": f"{cgst:.2f}",
            "igst": f"{igst:.2f}",
            "total_gst": f"{total_gst:.2f}",
            "sur": f"{sur:.2f}",
            "tax_free": f"{tax_free:.2f}",
            "exempted": f"{exempted:.2f}",
            "r_off": f"{r_off:.2f}",
        })

    seller = BusinessProfile.objects.first()
    seller_info = {
        "business_name": seller.business_name if seller else "DIVYA ENTERPRISES",
        "gstin": seller.gstin if seller else "",
    }

    totals = {
        "invoice_count": len(rows),
        "bill_amt": f"{tot_bill_amt:.2f}",
        "taxable": f"{tot_taxable:.2f}",
        "tax": f"{tot_tax:.2f}",
        "sgst": f"{tot_sgst:.2f}",
        "cgst": f"{tot_cgst:.2f}",
        "igst": f"{tot_igst:.2f}",
        "total_gst": f"{tot_total_gst:.2f}",
        "sur": "0.00",
        "tax_free": "0.00",
        "exempted": "0.00",
        "r_off": f"{tot_r_off:.2f}",
    }

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "seller": seller_info,
        "columns": [
            "DATE",
            "BILL NO.",
            "PARTY NAME",
            "GSTIN",
            "HSN",
            "BILL AMT.",
            "TAXABLE",
            "TAX",
            "SGST",
            "CGST",
            "IGST",
            "TOTAL GST",
            "SUR.",
            "TAX FREE",
            "EXEMPTED",
            "R.OFF",
        ],
        "rows": rows,
        "totals": totals,
    }


def build_sales_gst_report_xlsx(report_data):
    """Generate professional Excel workbook (.xlsx) for Sales GST Report."""
    import io
    from datetime import datetime
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales GST Report"

    title_font = Font(name="Calibri", size=14, bold=True, color="1E382B")
    subtitle_font = Font(name="Calibri", size=11, bold=True, color="2C4D3B")
    meta_font = Font(name="Calibri", size=10, italic=True, color="55695E")
    header_font = Font(name="Calibri", size=10, bold=True, color="1E382B")
    header_fill = PatternFill(start_color="E6EFE9", end_color="E6EFE9", fill_type="solid")
    data_font = Font(name="Calibri", size=10)
    total_font = Font(name="Calibri", size=10, bold=True, color="1E382B")
    total_fill = PatternFill(start_color="F2F6F3", end_color="F2F6F3", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="D4DED6"),
        right=Side(style="thin", color="D4DED6"),
        top=Side(style="thin", color="D4DED6"),
        bottom=Side(style="thin", color="D4DED6"),
    )
    header_border = Border(
        left=Side(style="thin", color="B0C4B8"),
        right=Side(style="thin", color="B0C4B8"),
        top=Side(style="medium", color="2C4D3B"),
        bottom=Side(style="medium", color="2C4D3B"),
    )
    total_border = Border(
        left=Side(style="thin", color="D4DED6"),
        right=Side(style="thin", color="D4DED6"),
        top=Side(style="thin", color="2C4D3B"),
        bottom=Side(style="double", color="2C4D3B"),
    )

    seller = report_data.get("seller", {})
    business_name = seller.get("business_name") or "DIVYA ENTERPRISES"
    ws["A1"] = business_name
    ws["A1"].font = title_font

    ws["A2"] = "SALES GST REPORT"
    ws["A2"].font = subtitle_font

    from_iso = report_data.get("from", "")
    to_iso = report_data.get("to", "")
    from_fmt = ""
    to_fmt = ""
    try:
        from_fmt = datetime.fromisoformat(from_iso).strftime("%d-%m-%Y")
    except Exception:
        from_fmt = from_iso
    try:
        to_fmt = datetime.fromisoformat(to_iso).strftime("%d-%m-%Y")
    except Exception:
        to_fmt = to_iso

    ws["A3"] = f"Period: {from_fmt} to {to_fmt}"
    ws["A3"].font = meta_font

    headers = [
        "DATE",
        "BILL NO.",
        "PARTY NAME",
        "GSTIN",
        "HSN",
        "BILL AMT.",
        "TAXABLE",
        "TAX",
        "SGST",
        "CGST",
        "IGST",
        "TOTAL GST",
        "SUR.",
        "TAX FREE",
        "EXEMPTED",
        "R.OFF",
    ]
    header_row = 5
    ws.row_dimensions[header_row].height = 24
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)

    rows = report_data.get("rows", [])
    current_row = 6
    num_fmt = "#,##0.00"

    for r in rows:
        c1 = ws.cell(row=current_row, column=1)
        try:
            d_val = datetime.strptime(r["date"], "%d-%m-%Y").date()
            c1.value = d_val
            c1.number_format = "DD-MM-YYYY"
        except Exception:
            c1.value = r.get("date", "")
        c1.font = data_font
        c1.border = thin_border
        c1.alignment = Alignment(horizontal="center", vertical="center")

        c2 = ws.cell(row=current_row, column=2, value=r.get("bill_no", ""))
        c2.font = data_font
        c2.border = thin_border
        c2.alignment = Alignment(horizontal="center", vertical="center")

        c3 = ws.cell(row=current_row, column=3, value=r.get("party_name", ""))
        c3.font = data_font
        c3.border = thin_border
        c3.alignment = Alignment(horizontal="left", vertical="center")

        c4 = ws.cell(row=current_row, column=4, value=r.get("gstin", ""))
        c4.font = data_font
        c4.border = thin_border
        c4.alignment = Alignment(horizontal="center", vertical="center")

        c5 = ws.cell(row=current_row, column=5, value=r.get("hsn", ""))
        c5.font = data_font
        c5.border = thin_border
        c5.alignment = Alignment(horizontal="center", vertical="center")

        num_keys = [
            "bill_amt",
            "taxable",
            "tax",
            "sgst",
            "cgst",
            "igst",
            "total_gst",
            "sur",
            "tax_free",
            "exempted",
            "r_off",
        ]
        for idx, key in enumerate(num_keys, 6):
            val_str = r.get(key, "0.00")
            c = ws.cell(row=current_row, column=idx, value=float(Decimal(str(val_str))))
            c.font = data_font
            c.border = thin_border
            c.number_format = num_fmt
            c.alignment = Alignment(horizontal="right", vertical="center")

        current_row += 1

    total_row = current_row
    c_tot_label = ws.cell(row=total_row, column=1, value="TOTAL")
    c_tot_label.font = total_font
    c_tot_label.fill = total_fill
    c_tot_label.border = total_border
    c_tot_label.alignment = Alignment(horizontal="left", vertical="center")

    for col_idx in range(2, 6):
        c = ws.cell(row=total_row, column=col_idx, value="")
        c.font = total_font
        c.fill = total_fill
        c.border = total_border

    totals = report_data.get("totals", {})
    last_data_row = current_row - 1
    num_cols = [
        (6, "bill_amt"),
        (7, "taxable"),
        (8, "tax"),
        (9, "sgst"),
        (10, "cgst"),
        (11, "igst"),
        (12, "total_gst"),
        (13, "sur"),
        (14, "tax_free"),
        (15, "exempted"),
        (16, "r_off"),
    ]

    for col_idx, key in num_cols:
        col_letter = get_column_letter(col_idx)
        c = ws.cell(row=total_row, column=col_idx)
        if len(rows) > 0:
            c.value = f"=SUM({col_letter}6:{col_letter}{last_data_row})"
        else:
            c.value = float(Decimal(str(totals.get(key, "0.00"))))
        c.font = total_font
        c.fill = total_fill
        c.border = total_border
        c.number_format = num_fmt
        c.alignment = Alignment(horizontal="right", vertical="center")

    ws.freeze_panes = "A6"
    if len(rows) > 0:
        ws.auto_filter.ref = f"A5:P{last_data_row}"

    col_widths = {
        "A": 13,  # DATE
        "B": 15,  # BILL NO.
        "C": 32,  # PARTY NAME
        "D": 18,  # GSTIN
        "E": 14,  # HSN
        "F": 14,  # BILL AMT.
        "G": 14,  # TAXABLE
        "H": 12,  # TAX
        "I": 12,  # SGST
        "J": 12,  # CGST
        "K": 12,  # IGST
        "L": 14,  # TOTAL GST
        "M": 11,  # SUR.
        "N": 12,  # TAX FREE
        "O": 13,  # EXEMPTED
        "P": 11,  # R.OFF
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


class SalesGstReportView(APIView):
    """Invoice-level Sales GST Report for POSTED invoices."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        data = get_sales_gst_report_data(from_date, to_date)
        return Response(data, status=status.HTTP_200_OK)


class SalesGstReportExportView(APIView):
    """Generate and download Excel (.xlsx) for the Sales GST Report."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        data = get_sales_gst_report_data(from_date, to_date)
        xlsx_bytes = build_sales_gst_report_xlsx(data)

        from_str = from_date.strftime("%Y%m%d")
        to_str = to_date.strftime("%Y%m%d")
        filename = f"sales-gst-report-{from_str}-{to_str}.xlsx"

        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
