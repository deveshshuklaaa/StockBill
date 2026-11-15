from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0016_clear_draft_invoice_numbers"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.CheckConstraint(
                condition=models.Q(("state", "DRAFT"), ("invoice_number__isnull", False), _connector="OR"),
                name="billing_invoice_number_required_unless_draft",
            ),
        ),
        # Step 1 of 3: nullable so existing credit notes can be backfilled.
        migrations.AddField(
            model_name="creditnote",
            name="credit_note_number",
            field=models.CharField(max_length=16, null=True, unique=True),
        ),
    ]
