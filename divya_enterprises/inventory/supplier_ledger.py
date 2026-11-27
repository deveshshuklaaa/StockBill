"""Supplier ledger (accounts payable): the mirror image of the customer side.

SIGN CONVENTION (used by the balance, the statement, the API and the UI)
------------------------------------------------------------------------
    balance = Σ posted purchases            (credits: we owe more)
            + Σ replacement receipts        (credits: goods received back)
            + Σ payment reversals           (credits: a payment undone)
            − Σ payments                    (debits: we paid)
            − Σ supplier returns            (debits: goods sent back)

    balance > 0  →  PAYABLE  (you owe the supplier)
    balance < 0  →  ADVANCE  (you have paid ahead)
    balance = 0  →  SETTLED

Example: a ₹1,00,000 round advance followed by a ₹97,368 purchase leaves
balance = 97,368 − 1,00,000 = −2,632, i.e. a ₹2,632 advance.

Only POSTED purchases count; drafts are not bills yet and a cancelled
purchase is no longer owed. A 1:1 damaged-goods replacement nets to zero:
the return is a debit and its replacement receipt a credit of the same
value (the replacement is valued at the return's unit cost).

There is deliberately no opening balance: the ledger starts with the first
recorded purchase or payment. A date-filtered statement only carries the
balance of the earlier entries forward ("brought forward"); nothing is
seeded or stored.

Payments and reversals are append-only (model guards + DB trigger), exactly
like billing.Payment / billing.PaymentReversal.
"""

import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from billing.models import AuditLog, BusinessProfile

from .models import (
    PurchaseInvoice,
    Supplier,
    SupplierPayment,
    SupplierPaymentReversal,
    SupplierReplacementReceipt,
    SupplierReturn,
)

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0.00")

STATUS_PAYABLE = "PAYABLE"
STATUS_ADVANCE = "ADVANCE"
STATUS_SETTLED = "SETTLED"

KIND_ORDER = {
    "purchase": 0,
    "supplier_return": 1,
    "replacement": 2,
    "payment": 3,
    "payment_reversal": 4,
}


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def balance_status(balance):
    if balance > 0:
        return STATUS_PAYABLE
    if balance < 0:
        return STATUS_ADVANCE
    return STATUS_SETTLED


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))["total"] or ZERO


def supplier_balance(supplier):
    """Current payable (+) / advance (−) for ``supplier``. See module docstring."""
    purchases = _sum(
        PurchaseInvoice.objects.filter(supplier=supplier, state=PurchaseInvoice.STATE_POSTED),
        "total_amount",
    )
    payments = _sum(SupplierPayment.objects.filter(supplier=supplier), "amount")
    reversals = _sum(SupplierPaymentReversal.objects.filter(payment__supplier=supplier), "amount")
    returns = _sum(SupplierReturn.objects.filter(supplier=supplier), "value")
    replacements = _sum(
        SupplierReplacementReceipt.objects.filter(supplier_return__supplier=supplier), "value"
    )
    return _money(purchases + replacements + reversals - payments - returns)


def _local_date(moment):
    return timezone.localtime(moment).date()


def _ledger_entries(supplier):
    """Every ledger entry for the supplier, oldest first, without balances."""
    entries = []
    for purchase in PurchaseInvoice.objects.filter(
        supplier=supplier, state=PurchaseInvoice.STATE_POSTED
    ).order_by("invoice_date", "id"):
        reference = purchase.purchase_number or f"Purchase #{purchase.pk}"
        if purchase.supplier_invoice_no:
            reference = f"{reference} · bill {purchase.supplier_invoice_no}"
        entries.append({
            "kind": "purchase", "id": purchase.pk, "date": purchase.invoice_date,
            "type_label": "Purchase", "reference": reference,
            "debit": None, "credit": purchase.total_amount, "sort_key": purchase.posted_at or purchase.created_at,
        })

    payments = SupplierPayment.objects.filter(supplier=supplier).prefetch_related("reversals").order_by("payment_date", "id")
    for payment in payments:
        reversed_amount = sum((r.amount for r in payment.reversals.all()), ZERO)
        entries.append({
            "kind": "payment", "id": payment.pk, "date": payment.payment_date,
            "type_label": "Payment", "reference": payment.reference or f"Payment #{payment.pk}",
            "mode": payment.mode, "mode_label": payment.get_mode_display(),
            "debit": payment.amount, "credit": None,
            "reversible_amount": _money(payment.amount - reversed_amount),
            "sort_key": payment.created_at,
        })
        for reversal in sorted(payment.reversals.all(), key=lambda r: r.pk):
            entries.append({
                "kind": "payment_reversal", "id": reversal.pk, "date": _local_date(reversal.created_at),
                "type_label": "Payment reversal", "reference": f"Reversal of payment #{payment.pk}: {reversal.reason}",
                "debit": None, "credit": reversal.amount, "sort_key": reversal.created_at,
            })

    for supplier_return in SupplierReturn.objects.filter(supplier=supplier).select_related("product").order_by("return_date", "id"):
        entries.append({
            "kind": "supplier_return", "id": supplier_return.pk, "date": supplier_return.return_date,
            "type_label": "Goods returned",
            "reference": f"{supplier_return.display_number} · {supplier_return.quantity.normalize():f} × {supplier_return.product.name}",
            "debit": supplier_return.value, "credit": None, "sort_key": supplier_return.created_at,
        })

    for receipt in SupplierReplacementReceipt.objects.filter(
        supplier_return__supplier=supplier
    ).select_related("supplier_return__product").order_by("receipt_date", "id"):
        entries.append({
            "kind": "replacement", "id": receipt.pk, "date": receipt.receipt_date,
            "type_label": "Replacement received",
            "reference": f"For {receipt.supplier_return.display_number} · {receipt.quantity.normalize():f} × {receipt.supplier_return.product.name}",
            "debit": None, "credit": receipt.value, "sort_key": receipt.created_at,
        })

    entries.sort(key=lambda e: (e["date"], KIND_ORDER[e["kind"]], e["sort_key"], e["id"]))
    for entry in entries:
        entry.pop("sort_key")
    return entries


def _entry_delta(entry):
    return Decimal(entry["credit"] or 0) - Decimal(entry["debit"] or 0)


def supplier_statement(supplier, from_date=None, to_date=None):
    """Chronological statement with a running balance (see sign convention).

    Entries before ``from_date`` are summed into ``opening_balance``
    (brought forward); entries after ``to_date`` are left out, so
    ``closing_balance`` is the balance as of ``to_date``.
    ``current_balance`` is always the all-time balance.
    """
    opening = ZERO
    in_range = []
    for entry in _ledger_entries(supplier):
        if from_date and entry["date"] < from_date:
            opening += _entry_delta(entry)
            continue
        if to_date and entry["date"] > to_date:
            continue
        in_range.append(entry)

    running = opening
    total_debit = ZERO
    total_credit = ZERO
    for entry in in_range:
        running += _entry_delta(entry)
        entry["balance"] = _money(running)
        total_debit += Decimal(entry["debit"] or 0)
        total_credit += Decimal(entry["credit"] or 0)

    current = supplier_balance(supplier)
    profile = BusinessProfile.objects.first()
    return {
        "business": {
            "business_name": profile.business_name if profile else "",
            "gstin": profile.gstin if profile else "",
            "registered_address": profile.registered_address if profile else "",
            "phone": profile.phone if profile else "",
        },
        "supplier": {
            "id": supplier.pk,
            "name": supplier.name,
            "gstin": supplier.gstin,
            "contact_info": supplier.contact_info,
            "address": supplier.address,
            "state": supplier.state,
            "state_code": supplier.state_code,
        },
        "from": from_date,
        "to": to_date,
        "sign_convention": "Balance > 0 = Payable (you owe the supplier); balance < 0 = Advance (you have paid ahead).",
        "opening_balance": _money(opening),
        "opening_status": balance_status(opening),
        "entries": in_range,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
        "closing_balance": _money(running),
        "closing_status": balance_status(running),
        "current_balance": current,
        "current_status": balance_status(current),
    }


@transaction.atomic
def create_supplier_payment(*, supplier, amount, created_by, payment_date=None, mode=SupplierPayment.MODE_BANK_TRANSFER, reference="", notes=""):
    """Record money paid to a supplier (an advance or against bills alike)."""
    amount = _money(amount)
    if amount <= 0:
        raise serializers.ValidationError({"amount": "Payment amount must be greater than zero."})
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=amount,
        payment_date=payment_date or timezone.localdate(),
        mode=mode,
        reference=(reference or "").strip(),
        notes=notes or "",
        created_by=created_by,
    )
    AuditLog.objects.create(
        user=created_by, action="supplier_payment_recorded", entity_type="SupplierPayment",
        entity_id=payment.pk, metadata={"supplier_id": supplier.pk, "amount": str(amount), "mode": mode},
    )
    return payment


@transaction.atomic
def reverse_supplier_payment(*, payment_id, amount, reversed_by, reason):
    """Undo all or part of a supplier payment; mirrors billing.reverse_payment."""
    payment = SupplierPayment.objects.select_for_update().get(pk=payment_id)
    amount = _money(amount)
    reversed_amount = _sum(SupplierPaymentReversal.objects.filter(payment=payment), "amount")
    if amount <= 0 or reversed_amount + amount > payment.amount:
        raise serializers.ValidationError({"amount": "Reversal exceeds the remaining payment amount."})
    reversal = SupplierPaymentReversal.objects.create(payment=payment, amount=amount, reason=reason, reversed_by=reversed_by)
    AuditLog.objects.create(
        user=reversed_by, action="supplier_payment_reversed", entity_type="SupplierPayment",
        entity_id=payment.pk, metadata={"amount": str(amount), "reason": reason},
    )
    return reversal


def _fmt_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d-%m-%Y")


def _balance_text(balance):
    status = balance_status(balance)
    if status == STATUS_SETTLED:
        return "0.00 (Settled)"
    return f"{abs(balance):,.2f} {status.title()}"


def build_supplier_statement_xlsx(statement):
    """Printable supplier statement (.xlsx), styled like the Sales GST export."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Supplier Statement"

    title_font = Font(name="Calibri", size=14, bold=True, color="1E382B")
    subtitle_font = Font(name="Calibri", size=11, bold=True, color="2C4D3B")
    meta_font = Font(name="Calibri", size=10, italic=True, color="55695E")
    label_font = Font(name="Calibri", size=10, bold=True, color="55695E")
    header_font = Font(name="Calibri", size=10, bold=True, color="1E382B")
    header_fill = PatternFill(start_color="E6EFE9", end_color="E6EFE9", fill_type="solid")
    data_font = Font(name="Calibri", size=10)
    total_font = Font(name="Calibri", size=10, bold=True, color="1E382B")
    total_fill = PatternFill(start_color="F2F6F3", end_color="F2F6F3", fill_type="solid")
    thin = Side(style="thin", color="D4DED6")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_border = Border(
        left=Side(style="thin", color="B0C4B8"), right=Side(style="thin", color="B0C4B8"),
        top=Side(style="medium", color="2C4D3B"), bottom=Side(style="medium", color="2C4D3B"),
    )
    total_border = Border(left=thin, right=thin, top=Side(style="thin", color="2C4D3B"), bottom=Side(style="double", color="2C4D3B"))
    money_format = '#,##0.00'

    business = statement["business"]
    supplier = statement["supplier"]
    ws["A1"] = business.get("business_name") or "DIVYA ENTERPRISES"
    ws["A1"].font = title_font
    header_bits = [bit for bit in [business.get("registered_address"), business.get("gstin") and f"GSTIN {business['gstin']}", business.get("phone")] if bit]
    ws["A2"] = " · ".join(header_bits)
    ws["A2"].font = meta_font
    ws["A3"] = "SUPPLIER STATEMENT"
    ws["A3"].font = subtitle_font

    details = [
        ("Supplier", supplier["name"]),
        ("GSTIN", supplier.get("gstin") or "Not recorded"),
        ("Contact", supplier.get("contact_info") or ""),
        ("Address", " ".join(bit for bit in [supplier.get("address"), supplier.get("state")] if bit)),
        ("Period", f"{_fmt_date(statement['from']) or 'Start'} to {_fmt_date(statement['to']) or _fmt_date(timezone.localdate())}"),
        ("Generated", timezone.localtime().strftime("%d-%m-%Y %H:%M")),
    ]
    row = 5
    for label, value in details:
        ws.cell(row=row, column=1, value=label).font = label_font
        ws.cell(row=row, column=2, value=value).font = data_font
        row += 1

    header_row = row + 1
    headers = ["DATE", "TYPE", "REFERENCE", "DEBIT (PAID / RETURNED)", "CREDIT (PURCHASED)", "BALANCE", "PAYABLE / ADVANCE"]
    for col, text in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=text)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    current = header_row + 1

    def write_row(values, font=data_font, fill=None, border=thin_border):
        nonlocal current
        for col, value in enumerate(values, 1):
            cell = ws.cell(row=current, column=col, value=value)
            cell.font = font
            cell.border = border
            if fill is not None:
                cell.fill = fill
            if col in (4, 5, 6) and isinstance(value, (int, float, Decimal)):
                cell.number_format = money_format
                cell.alignment = Alignment(horizontal="right")
        current += 1

    if statement["from"]:
        opening = statement["opening_balance"]
        write_row([_fmt_date(statement["from"]), "Brought forward", "Balance of earlier entries", None, None, float(opening), _balance_text(opening)])
    for entry in statement["entries"]:
        reference = entry["reference"] + (f" · {entry['mode_label']}" if entry.get("mode_label") else "")
        write_row([
            _fmt_date(entry["date"]), entry["type_label"], reference,
            float(entry["debit"]) if entry["debit"] is not None else None,
            float(entry["credit"]) if entry["credit"] is not None else None,
            float(entry["balance"]), _balance_text(entry["balance"]),
        ])
    closing = statement["closing_balance"]
    write_row(
        ["", "CLOSING", "", float(statement["total_debit"]), float(statement["total_credit"]), float(closing), _balance_text(closing)],
        font=total_font, fill=total_fill, border=total_border,
    )
    note = ws.cell(row=current + 1, column=1, value=statement["sign_convention"])
    note.font = meta_font

    for letter, width in {"A": 12, "B": 22, "C": 52, "D": 22, "E": 20, "F": 16, "G": 22}.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = f"A{header_row + 1}"

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
