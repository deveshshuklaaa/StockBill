"""Shared Excel (.xlsx) download builder for StockBill exports.

Every export goes through ``xlsx_response`` so all files look and behave
the same:

* Title row, an IST "Generated" line, then a bold header row with frozen
  panes, filter dropdowns and sensible column widths.
* Text columns are real text cells (``@`` format). A value that looks like
  a formula (``=HYPERLINK(...)``) is stored as plain text, so Excel never
  evaluates it, and codes such as phone numbers, pincodes and state codes
  keep every digit and leading zero.
* Money and quantity columns are real numbers, so totals and sorting work.
* Multi-line text (addresses) is flattened to one line joined by ", ".
* Filenames carry an IST timestamp: ``stockbill-<name>-YYYYMMDD-HHMM.xlsx``.
"""

import io
import re
from dataclasses import dataclass
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TEXT = "text"
MONEY = "money"
QUANTITY = "quantity"
INTEGER = "integer"

MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")
_NUMBER_FORMATS = {TEXT: "@", MONEY: "#,##0.00", QUANTITY: "#,##0", INTEGER: "0"}
# Quantities with a fractional part (e.g. 12.5 kg) show up to 3 decimals;
# whole quantities use "#,##0" so they do not render as "12.".
FRACTIONAL_QUANTITY_FORMAT = "#,##0.0##"
_LINE_BREAKS = re.compile(r"[\r\n]+")
HEADER_ROW = 4  # title, generated line, blank row, then headers


@dataclass(frozen=True)
class Column:
    header: str
    kind: str = TEXT
    width: int = 18


def flatten_text(value):
    """String form of a text cell: line breaks collapsed to ", ", control characters removed."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if value is None:
        return ""
    text = str(value)
    if "\n" in text or "\r" in text:
        parts = (part.strip() for part in _LINE_BREAKS.split(text))
        text = ", ".join(part for part in parts if part)
    return ILLEGAL_CHARACTERS_RE.sub("", text)


def _number(value, kind):
    if value is None or value == "":
        return None
    if kind == MONEY:
        return Decimal(value).quantize(MONEY_QUANTUM)
    if kind == QUANTITY:
        return Decimal(value).quantize(QUANTITY_QUANTUM)
    return int(value)


def export_filename(name):
    return f"stockbill-{name}-{timezone.localtime().strftime('%Y%m%d-%H%M')}.xlsx"


def xlsx_response(*, title, columns, rows, filename, subtitle=""):
    """Build an .xlsx attachment. ``rows`` are sequences in ``columns`` order."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = title[:31]

    sheet.cell(row=1, column=1, value=flatten_text(title)).font = Font(size=14, bold=True, color="1E382B")
    generated = f"Generated {timezone.localtime().strftime('%d-%m-%Y %H:%M')} IST"
    sheet.cell(row=2, column=1, value=flatten_text(f"{generated} · {subtitle}" if subtitle else generated)).font = Font(
        size=10, italic=True, color="55695E"
    )

    header_font = Font(bold=True, color="1E382B")
    header_fill = PatternFill(start_color="E6EFE9", end_color="E6EFE9", fill_type="solid")
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=HEADER_ROW, column=index, value=column.header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        sheet.column_dimensions[get_column_letter(index)].width = column.width

    row_number = HEADER_ROW
    for row in rows:
        if len(row) != len(columns):
            raise ValueError(f"Row has {len(row)} cells, expected {len(columns)}.")
        row_number += 1
        for index, (column, value) in enumerate(zip(columns, row), start=1):
            if column.kind == TEXT:
                text = flatten_text(value)
                cell = sheet.cell(row=row_number, column=index)
                if text:
                    cell.value = text
                    # openpyxl treats strings starting with "=" as formulas; force plain text.
                    cell.data_type = "s"
            else:
                number = _number(value, column.kind)
                cell = sheet.cell(row=row_number, column=index, value=number)
                cell.alignment = Alignment(horizontal="right")
            cell.number_format = _NUMBER_FORMATS[column.kind]
            if column.kind == QUANTITY and number is not None and number != number.to_integral_value():
                cell.number_format = FRACTIONAL_QUANTITY_FORMAT

    last_column = get_column_letter(len(columns))
    sheet.freeze_panes = sheet.cell(row=HEADER_ROW + 1, column=1)
    sheet.auto_filter.ref = f"A{HEADER_ROW}:{last_column}{max(row_number, HEADER_ROW)}"

    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
