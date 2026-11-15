from django.db import migrations


def clear_draft_numbers(apps, schema_editor):
    """Drop the browser-generated numbers from DRAFT invoices only.

    Drafts are not tax invoices; they receive a real number when posted.
    POSTED and CANCELLED rows are not touched (the immutability trigger
    would reject it anyway), so every issued legacy INV-... number stays.
    """
    Invoice = apps.get_model("billing", "Invoice")
    Invoice.objects.filter(state="DRAFT").update(invoice_number=None)


def restore_draft_placeholders(apps, schema_editor):
    """Backwards: give drafts a unique placeholder so NOT NULL can return."""
    Invoice = apps.get_model("billing", "Invoice")
    for invoice in Invoice.objects.filter(state="DRAFT", invoice_number__isnull=True).only("id"):
        Invoice.objects.filter(pk=invoice.pk).update(invoice_number=f"DRAFT-{invoice.pk}")


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0015_invoice_document_numbering"),
    ]

    operations = [
        migrations.RunPython(clear_draft_numbers, restore_draft_placeholders),
    ]
