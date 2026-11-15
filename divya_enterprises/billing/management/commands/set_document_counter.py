"""Set where a GST document-number series continues from (admin operations tool).

Example: the CA decides FY 26-27 tax invoices must continue after serial 412:

    python manage.py set_document_counter --doc invoice --fy 26-27 --last-serial 412

The next posted invoice is then DE/26-27/00413. The command refuses to move a
counter below a serial already issued in that series (which would re-issue a
number), prints old -> new, and records an AuditLog row.
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from billing.models import AuditLog
from billing.numbering import CREDIT_NOTE, INVOICE, DocumentNumberError, format_document_number, series_prefix, set_counter

FY_RE = re.compile(r"^\d{2}-\d{2}$")


class Command(BaseCommand):
    help = "Set the last issued serial of the invoice or credit-note number series for a financial year."

    def add_arguments(self, parser):
        parser.add_argument("--doc", required=True, choices=[INVOICE, CREDIT_NOTE])
        parser.add_argument("--fy", required=True, help="Financial year code, e.g. 26-27")
        parser.add_argument("--last-serial", required=True, type=int, dest="last_serial", help="Serial the next document follows")

    def handle(self, *args, doc, fy, last_serial, **options):
        if not FY_RE.fullmatch(fy) or (int(fy[:2]) + 1) % 100 != int(fy[3:]):
            raise CommandError(f"--fy must look like 26-27 (got {fy!r}).")
        try:
            with transaction.atomic():
                counter_pk, old, new = set_counter(doc, fy, last_serial)
                AuditLog.objects.create(
                    user=None,
                    action="document_counter_set",
                    entity_type="InvoiceNumberCounter" if doc == INVOICE else "CreditNoteNumberCounter",
                    entity_id=counter_pk,
                    metadata={"doc": doc, "fy": fy, "old_last_serial": old, "new_last_serial": new},
                )
        except DocumentNumberError as exc:
            raise CommandError(str(exc)) from exc
        next_number = format_document_number(series_prefix(doc), fy, new + 1)
        self.stdout.write(self.style.SUCCESS(f"{doc} counter for FY {fy}: {old} -> {new}. Next number: {next_number}"))
