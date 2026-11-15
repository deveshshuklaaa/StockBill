"""Shared CSV download builder for StockBill exports.

Every export goes through ``csv_response`` so all files behave the same in
Excel on Windows:

* UTF-8 with a BOM, so ₹ and Hindi/Marathi names display correctly.
* Python's ``csv`` writer (QUOTE_MINIMAL); never string concatenation.
* Formula-injection protection on *text* columns only: a cell starting with
  ``=``, ``+``, ``-``, ``@``, tab or carriage return gets a leading ``'``.
  Numeric columns are never touched, so ``-1500.00`` stays a number.
* Multi-line text (addresses) is flattened to one line joined by ", ".
* Code-like text (phone, pincode, state code) can be marked ``excel_text``:
  written as ``="value"`` so Excel keeps it as text instead of turning
  ``919820098200`` into ``9.2E+11`` or dropping the leading 0 of ``07``.
  The value sits inside a string literal with quotes doubled, so Excel
  never evaluates it.
* Money has 2 decimals, quantities 3; no separators or currency symbols.
* Filenames carry an IST timestamp: ``stockbill-<name>-YYYYMMDD-HHMM.csv``.
"""

import csv
import io
import re
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_LINE_BREAKS = re.compile(r"[\r\n]+")


def money(value):
    return "" if value is None else str(Decimal(value).quantize(MONEY_QUANTUM))


def quantity(value):
    return "" if value is None else str(Decimal(value).quantize(QUANTITY_QUANTUM))


def yes_no(value):
    return "Yes" if value else "No"


def ist_datetime(value):
    """ISO date-time in IST (Asia/Kolkata), or empty for None."""
    return "" if value is None else timezone.localtime(value).isoformat(timespec="seconds")


def _flatten(value):
    """String form of a cell with line breaks collapsed to ", "."""
    if value is None:
        return ""
    text = str(value)
    if "\n" in text or "\r" in text:
        parts = (part.strip() for part in _LINE_BREAKS.split(text))
        text = ", ".join(part for part in parts if part)
    return text


def safe_text(value):
    """Flatten line breaks and neutralise spreadsheet formulas in a text cell."""
    text = _flatten(value)
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    return text


# Excel rejects string literals longer than this inside a formula.
_EXCEL_LITERAL_LIMIT = 255


def excel_text(value):
    """Force Excel to keep a code-like value as text: ``="value"``.

    The value is a string literal with quotes doubled, so it is displayed,
    never evaluated. Values too long for an Excel literal fall back to
    ``safe_text``.
    """
    text = _flatten(value)
    if not text:
        return ""
    if len(text) > _EXCEL_LITERAL_LIMIT:
        return safe_text(text)
    return '="' + text.replace('"', '""') + '"'


def export_filename(name):
    return f"stockbill-{name}-{timezone.localtime().strftime('%Y%m%d-%H%M')}.csv"


def csv_response(*, headers, rows, filename, text_columns, excel_text_columns=()):
    """Build a CSV attachment.

    ``rows`` are sequences in ``headers`` order. Columns named in
    ``text_columns`` get ``safe_text``; those also named in
    ``excel_text_columns`` are written with ``excel_text``. Every other
    column must already be a formatted number/flag string (use
    ``money``/``quantity``/``yes_no``).
    """
    unknown = (set(text_columns) | set(excel_text_columns)) - set(headers)
    if unknown:
        raise ValueError(f"columns not in headers: {sorted(unknown)}")
    if set(excel_text_columns) - set(text_columns):
        raise ValueError("excel_text_columns must also be text_columns.")
    text_indexes = {index for index, header in enumerate(headers) if header in text_columns}
    excel_indexes = {index for index, header in enumerate(headers) if header in excel_text_columns}

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        if len(row) != len(headers):
            raise ValueError(f"Row has {len(row)} cells, expected {len(headers)}.")
        writer.writerow(
            excel_text(cell) if index in excel_indexes
            else safe_text(cell) if index in text_indexes
            else ("" if cell is None else cell)
            for index, cell in enumerate(row)
        )

    response = HttpResponse(buffer.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
