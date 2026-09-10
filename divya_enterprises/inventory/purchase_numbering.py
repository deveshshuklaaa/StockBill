"""Financial-year purchase document numbering: PI/26-27/000001."""

from datetime import date

from django.db import connection
from django.db.models import F

from .models import PurchaseNumberCounter


def financial_year_code(for_date):
    """Return the Indian FY code like '26-27' for a date (Apr 1 - Mar 31)."""
    year = for_date.year
    start = year if for_date.month >= 4 else year - 1
    return f"{start % 100:02d}-{start % 100 + 1:02d}"


def _next_serial(fy_code):
    """Reserve the next serial inside the caller's transaction.

    A transaction-scoped advisory lock on the FY key serializes concurrent
    posts; the counter row is created on demand under that lock, so the
    insert race is impossible. If the surrounding purchase post rolls back,
    the reservation rolls back too and the numbering stays gapless.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [fy_code])
    counter, _ = PurchaseNumberCounter.objects.get_or_create(fy_code=fy_code)
    PurchaseNumberCounter.objects.filter(pk=counter.pk).update(
        last_serial=F("last_serial") + 1
    )
    counter.refresh_from_db()
    return counter.last_serial


def next_purchase_number(for_date=None):
    """Return the next purchase number for the date's financial year.

    Must be called inside a transaction (purchase posting is atomic).
    """
    fy_code = financial_year_code(for_date or date.today())
    serial = _next_serial(fy_code)
    return f"PI/{fy_code}/{serial:06d}"


def peek_next_number(for_date=None):
    """Preview the next number without reserving it (UI hint only)."""
    fy_code = financial_year_code(for_date or date.today())
    counter = PurchaseNumberCounter.objects.filter(fy_code=fy_code).first()
    serial = (counter.last_serial if counter else 0) + 1
    return f"PI/{fy_code}/{serial:06d}"
