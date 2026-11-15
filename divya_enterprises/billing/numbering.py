"""GST-compliant sales document numbering: DE/26-27/00001, CN/26-27/00001.

CGST Rule 46(b) (tax invoices) and Rule 53 (credit notes) require a
consecutive serial number of at most sixteen characters, using only letters,
digits, hyphen and slash, unique within a financial year.

This reuses the purchase-numbering pattern (``inventory.purchase_numbering``):
a transaction-scoped advisory lock serialises reservations, the per-FY counter
row is created on demand under that lock, and the increment happens inside the
caller's transaction. If the caller rolls back, the reservation rolls back with
it, so the series stays gapless.
"""

import re

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from inventory.purchase_numbering import financial_year_code

from .models import CreditNoteNumberCounter, InvoiceNumberCounter

GST_DOCUMENT_NUMBER_RE = re.compile(r"^[A-Za-z0-9/-]{1,16}$")
SERIAL_WIDTH = 5

INVOICE = "invoice"
CREDIT_NOTE = "credit_note"

# Distinct advisory-lock namespaces so invoice / credit-note numbering never
# contends with purchase numbering, which locks on hashtext(fy_code).
_SERIES = {
    INVOICE: {"lock_prefix": "INV:", "counter": InvoiceNumberCounter, "setting": "INVOICE_NUMBER_PREFIX", "default": "DE"},
    CREDIT_NOTE: {"lock_prefix": "CN:", "counter": CreditNoteNumberCounter, "setting": "CREDIT_NOTE_NUMBER_PREFIX", "default": "CN"},
}


class DocumentNumberError(ValueError):
    """Raised instead of ever emitting a non-compliant document number."""


def series_prefix(doc):
    config = _SERIES[doc]
    return getattr(settings, config["setting"], config["default"])


def format_document_number(prefix, fy_code, serial):
    number = f"{prefix}/{fy_code}/{serial:0{SERIAL_WIDTH}d}"
    if not GST_DOCUMENT_NUMBER_RE.fullmatch(number):
        raise DocumentNumberError(
            f"Refusing to issue non-compliant GST document number {number!r}: it must be at most "
            "16 characters of letters, digits, '/' or '-'. Check the configured prefix."
        )
    return number


def lock_series(doc, fy_code):
    """Take the transaction-scoped advisory lock for one document series."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_SERIES[doc]["lock_prefix"] + fy_code])


def _next_number(doc, for_date):
    if not connection.in_atomic_block:
        raise DocumentNumberError("Document numbers must be reserved inside the posting transaction.")
    prefix = series_prefix(doc)
    fy_code = financial_year_code(for_date or timezone.localdate())
    # Validate the shape before reserving so a bad prefix never consumes a serial.
    format_document_number(prefix, fy_code, 1)
    counter_model = _SERIES[doc]["counter"]
    lock_series(doc, fy_code)
    counter, _ = counter_model.objects.get_or_create(fy_code=fy_code)
    counter_model.objects.filter(pk=counter.pk).update(last_serial=F("last_serial") + 1)
    counter.refresh_from_db()
    return format_document_number(prefix, fy_code, counter.last_serial)


def next_invoice_number(for_date=None):
    """Reserve the next tax-invoice number. Call inside the posting transaction."""
    return _next_number(INVOICE, for_date)


def next_credit_note_number(for_date=None):
    """Reserve the next credit-note number. Call inside the creating transaction."""
    return _next_number(CREDIT_NOTE, for_date)


def max_issued_serial(doc, fy_code):
    """Highest serial already present on a document in the current-prefix series."""
    if doc == INVOICE:
        from .models import Invoice

        numbers = Invoice.objects.filter(invoice_number__startswith=f"{series_prefix(doc)}/{fy_code}/").values_list("invoice_number", flat=True)
    else:
        from .models import CreditNote

        numbers = CreditNote.objects.filter(credit_note_number__startswith=f"{series_prefix(doc)}/{fy_code}/").values_list("credit_note_number", flat=True)
    serials = [int(number.rsplit("/", 1)[1]) for number in numbers if number.rsplit("/", 1)[1].isdigit()]
    return max(serials, default=0)


@transaction.atomic
def set_counter(doc, fy_code, last_serial):
    """Move a series counter (operational tool for the FY starting point).

    Refuses to go below a serial already issued, which would re-issue a number.
    Returns (counter_pk, old_value, new_value).
    """
    if last_serial < 0:
        raise DocumentNumberError("last_serial cannot be negative.")
    prefix = series_prefix(doc)
    format_document_number(prefix, fy_code, max(last_serial + 1, 1))
    lock_series(doc, fy_code)
    counter_model = _SERIES[doc]["counter"]
    counter, _ = counter_model.objects.get_or_create(fy_code=fy_code)
    issued = max_issued_serial(doc, fy_code)
    if last_serial < issued:
        raise DocumentNumberError(
            f"Cannot set {doc} counter for {fy_code} to {last_serial}: serial {issued} has already been issued."
        )
    old = counter.last_serial
    counter_model.objects.filter(pk=counter.pk).update(last_serial=last_serial)
    return counter.pk, old, last_serial
