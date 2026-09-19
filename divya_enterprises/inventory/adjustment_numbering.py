"""Financial-year adjustment document numbering: ADJ/26-27/000001."""

from datetime import date

from django.db import connection
from django.db.models import F

from .models import StockAdjustmentNumberCounter
from .purchase_numbering import financial_year_code


def _next_serial(fy_code):
    """Reserve the next adjustment serial inside the caller's transaction.

    A transaction-scoped advisory lock on the FY key serializes concurrent
    posts; the counter row is created on demand under that lock. If the
    surrounding transaction rolls back, the counter update rolls back too
    and numbering remains gapless.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"ADJ_{fy_code}"])
    counter, _ = StockAdjustmentNumberCounter.objects.get_or_create(fy_code=fy_code)
    StockAdjustmentNumberCounter.objects.filter(pk=counter.pk).update(
        last_serial=F("last_serial") + 1
    )
    counter.refresh_from_db()
    return counter.last_serial


def next_adjustment_number(for_date=None):
    """Return the next adjustment number for the date's financial year.

    Must be called inside an atomic transaction when saving an adjustment.
    """
    fy_code = financial_year_code(for_date or date.today())
    serial = _next_serial(fy_code)
    return f"ADJ/{fy_code}/{serial:06d}"


def peek_next_adjustment_number(for_date=None):
    """Preview the next adjustment number without reserving it (UI hint only)."""
    fy_code = financial_year_code(for_date or date.today())
    counter = StockAdjustmentNumberCounter.objects.filter(fy_code=fy_code).first()
    serial = (counter.last_serial if counter else 0) + 1
    return f"ADJ/{fy_code}/{serial:06d}"
