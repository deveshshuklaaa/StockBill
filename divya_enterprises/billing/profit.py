"""Read-only profit calculations from historical invoice snapshots."""

from decimal import Decimal

from .models import Invoice


def profit_percent_on_cost(gross_profit, taxable_cogs):
    """Profit on pre-GST historical cost, using the business label Margin."""
    if taxable_cogs <= 0:
        return None
    return (gross_profit / taxable_cogs * Decimal("100")).quantize(Decimal("0.1"))


def _profit_totals(revenue, cogs):
    profit = revenue - cogs
    return {
        "taxable_sales_revenue": revenue,
        "taxable_cogs": cogs,
        "gross_profit": profit,
        "margin_percent": profit_percent_on_cost(profit, cogs),
    }


def get_invoice_profit_data(invoice):
    """Original issued amounts; credit notes do not restate this invoice.

    Draft costs are provisional. Cancelled invoices retain their original
    snapshots for reference, but are excluded from active financial reports.
    Uses prefetched lines when available, without reading today's prices/WAC.
    """
    if invoice.state not in (Invoice.STATE_POSTED, Invoice.STATE_CANCELLED):
        return None

    products = {}
    revenue = Decimal("0.00")
    cogs = Decimal("0.00")
    for line in invoice.line_items.all():
        key = (line.product_id, line.product_name_snapshot, line.base_unit_snapshot)
        row = products.setdefault(key, {
            "product_id": line.product_id,
            "product_name": line.product_name_snapshot,
            "base_unit": line.base_unit_snapshot,
            "base_quantity": Decimal("0.000"),
            "taxable_sales_revenue": Decimal("0.00"),
            "taxable_cogs": Decimal("0.00"),
        })
        row["base_quantity"] += line.base_quantity
        row["taxable_sales_revenue"] += line.taxable_value_snapshot
        row["taxable_cogs"] += line.cogs_amount
        revenue += line.taxable_value_snapshot
        cogs += line.cogs_amount

    for row in products.values():
        row.update(_profit_totals(row["taxable_sales_revenue"], row["taxable_cogs"]))

    return {**_profit_totals(revenue, cogs), "products": list(products.values())}
