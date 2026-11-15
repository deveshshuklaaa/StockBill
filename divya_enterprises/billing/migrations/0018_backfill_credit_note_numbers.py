import re
from collections import defaultdict

from django.conf import settings
from django.db import migrations

TABLE = "billing_creditnote"
TRIGGER = "stockbill_protect_billing_creditnote"
NUMBER_RE = re.compile(r"^[A-Za-z0-9/-]{1,16}$")


def _fy_code(for_date):
    # Same rule as inventory.purchase_numbering.financial_year_code (frozen
    # here because migrations must not depend on application code changing).
    start = for_date.year if for_date.month >= 4 else for_date.year - 1
    return f"{start % 100:02d}-{start % 100 + 1:02d}"


def backfill(apps, schema_editor):
    """Step 2 of 3: number existing credit notes in (created_at, id) order.

    billing_creditnote is append-only via the stockbill_protect_history
    trigger, so that one trigger is disabled for this backfill and enabled
    again in the same transaction. Only the new credit_note_number column is
    written; no financial value changes. The per-FY counter is advanced to
    the last serial used so new credit notes continue the series.
    """
    CreditNote = apps.get_model("billing", "CreditNote")
    Counter = apps.get_model("billing", "CreditNoteNumberCounter")
    prefix = getattr(settings, "CREDIT_NOTE_NUMBER_PREFIX", "CN")
    notes = list(CreditNote.objects.filter(credit_note_number__isnull=True).order_by("created_at", "id").values_list("id", "note_date"))
    if not notes:
        return
    is_postgres = schema_editor.connection.vendor == "postgresql"
    if is_postgres:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {TABLE} DISABLE TRIGGER {TRIGGER}")
    try:
        serials = defaultdict(int)
        for counter in Counter.objects.all():
            serials[counter.fy_code] = counter.last_serial
        for note_id, note_date in notes:
            fy_code = _fy_code(note_date)
            serials[fy_code] += 1
            number = f"{prefix}/{fy_code}/{serials[fy_code]:05d}"
            if not NUMBER_RE.fullmatch(number):
                raise ValueError(f"Credit note backfill would produce non-compliant number {number!r}.")
            CreditNote.objects.filter(pk=note_id).update(credit_note_number=number)
        for fy_code, last_serial in serials.items():
            Counter.objects.update_or_create(fy_code=fy_code, defaults={"last_serial": last_serial})
    finally:
        if is_postgres:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE {TABLE} ENABLE TRIGGER {TRIGGER}")


def unbackfill(apps, schema_editor):
    """Backwards: the column is dropped by 0017's reversal; reset counters."""
    Counter = apps.get_model("billing", "CreditNoteNumberCounter")
    Counter.objects.all().update(last_serial=0)


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0017_invoice_number_constraint_creditnote_number"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
