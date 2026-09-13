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
  gross_profit  = Σ (line_total − cogs) per line, aggregated

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
  POSTED lines only. revenue = Σ line_total, cogs = Σ cogs_amount
  (historical snapshots), gross_profit = revenue − cogs.
  Credit notes reduce revenue and COGS proportionally.
  Per-product and per-customer breakdowns aggregate the same terms.

TOP PRODUCTS — /api/reports/top-products/
  POSTED lines only, ranked by quantity / revenue / profit (historical
  snapshots). Date range required.

DASHBOARD — /api/reports/dashboard/
  Every number comes from the same queries above (today's posted sales and
  purchases, inventory valuation total, customer outstanding, active
  counts, low stock by low_stock_threshold, period gross profit).

All endpoints are read-only GET with IsAuthenticated; financial reports
(profit, tax, dashboard financial section, customer sales) additionally
require admin via IsAdminUser, matching existing report policy.
"""

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

from .models import CreditNoteLineItem, Invoice, InvoiceLineItem, Payment

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
        revenue = totals["net_sales"] or ZERO_MONEY
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
                "taxable_sales": totals["taxable_sales"],
                "gst": gst,
                "cgst": totals["cgst"],
                "sgst": totals["sgst"],
                "igst": totals["igst"],
                "net_sales": revenue,
                "cogs": totals["cogs"],
                "gross_profit": revenue - (totals["cogs"] or ZERO_MONEY),
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
                quantity_sold=Coalesce(Sum("quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
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
            .order_by("-sales_value")
        )
        products = []
        total_cogs = ZERO_MONEY
        total_revenue = ZERO_MONEY
        for row in rows:
            revenue = row["sales_value"] or ZERO_MONEY
            cogs = row["cogs"] or ZERO_MONEY
            profit = revenue - cogs
            total_cogs += cogs
            total_revenue += revenue
            products.append(
                {
                    "product_id": row["product_id"],
                    "product_name": row["product__name"],
                    "variant_snapshot": row["product_name_snapshot"],
                    "base_unit": row["base_unit_snapshot"],
                    "quantity_sold": row["quantity_sold"],
                    "gross_sales": row["gross_sales"],
                    "discounts": row["discounts"],
                    "taxable_sales": row["taxable_sales"],
                    "gst": row["gst"],
                    "sales_value": revenue,
                    "cogs": cogs,
                    "gross_profit": profit,
                    "margin_percent": (
                        (profit / revenue * Decimal("100")).quantize(Decimal("0.1"))
                        if revenue > 0
                        else None
                    ),
                }
            )
        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED lines only; COGS is the historical cogs_amount snapshot, never current cost or WAC.",
                "products": products,
                "total_revenue": total_revenue,
                "total_cogs": total_cogs,
                "total_gross_profit": total_revenue - total_cogs,
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


class ProfitReportView(APIView):
    """Gross profit = POSTED revenue − historical COGS snapshots."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            from_date, to_date = _date_range(request, required=True)
        except ValueError as error:
            return _bad_request(str(error))

        # Credit-note reversals reduce the effective revenue and COGS.
        lines = (
            _posted_invoice_lines(from_date, to_date)
            .annotate(
                reversed_quantity=Coalesce(
                    _credit_note_total_subquery("quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD
                ),
                reversed_revenue=Coalesce(
                    _credit_note_total_subquery("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD
                ),
                reversed_cogs=Coalesce(
                    _credit_note_total_subquery("quantity") * F("cost_price_snapshot"),
                    Value(ZERO_MONEY), output_field=MONEY_FIELD,
                ),
            )
            .annotate(
                effective_revenue=ExpressionWrapper(
                    F("line_total") - F("reversed_revenue"), output_field=MONEY_FIELD
                ),
                effective_cogs=ExpressionWrapper(
                    F("cogs_amount") - F("reversed_cogs"), output_field=MONEY_FIELD
                ),
            )
        )
        totals = lines.aggregate(
            revenue=Coalesce(Sum("effective_revenue"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cogs=Coalesce(Sum("effective_cogs"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        revenue = totals["revenue"] or ZERO_MONEY
        cogs = totals["cogs"] or ZERO_MONEY
        gross_profit = revenue - cogs

        by_product = list(
            lines.values("product_id", "product__name")
            .annotate(
                revenue=Coalesce(Sum("effective_revenue"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
                cogs=Coalesce(Sum("effective_cogs"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            )
            .order_by("-revenue")
        )

        return Response(
            {
                "from": from_date,
                "to": to_date,
                "rules": "POSTED lines only. Revenue = Σ line_total, COGS = historical cogs_amount snapshot (never current cost/WAC). Credit notes reduce both proportionally.",
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": gross_profit,
                "gross_margin_percent": (
                    (gross_profit / revenue * Decimal("100")).quantize(Decimal("0.1"))
                    if revenue > 0
                    else None
                ),
                "by_product": [
                    {
                        "product_id": row["product_id"],
                        "product_name": row["product__name"],
                        "revenue": row["revenue"],
                        "cogs": row["cogs"],
                        "gross_profit": (row["revenue"] or ZERO_MONEY) - (row["cogs"] or ZERO_MONEY),
                    }
                    for row in by_product
                ],
            }
        )


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
            "total_quantity": Coalesce(Sum("quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
            "total_revenue": Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
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

        profit_lines = _posted_invoice_lines(from_date, to_date)
        profit = profit_lines.aggregate(
            revenue=Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
            cogs=Coalesce(Sum("cogs_amount"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
        )
        revenue = profit["revenue"] or ZERO_MONEY
        cogs = profit["cogs"] or ZERO_MONEY

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
                total_quantity=Coalesce(Sum("quantity"), Value(ZERO_QTY), output_field=QUANTITY_FIELD),
                total_revenue=Coalesce(Sum("line_total"), Value(ZERO_MONEY), output_field=MONEY_FIELD),
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
                    "revenue": revenue,
                    "cogs": cogs,
                    "gross_profit": revenue - cogs,
                },
                "low_stock": low_stock,
                "recent_sales": recent_sales,
                "recent_purchases": recent_purchases,
                "top_products": list(top_products),
            }
        )
