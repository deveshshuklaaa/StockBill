from django.db import migrations


TRIGGER_FUNCTION = r'''
CREATE OR REPLACE FUNCTION stockbill_protect_history() RETURNS trigger AS $$
DECLARE
    invoice_state text;
BEGIN
    IF TG_TABLE_NAME = 'billing_invoice' THEN
        IF TG_OP = 'DELETE' AND OLD.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Only draft invoices can be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.state IN ('POSTED', 'CANCELLED') THEN
            IF OLD.invoice_number IS DISTINCT FROM NEW.invoice_number
               OR OLD.customer_id IS DISTINCT FROM NEW.customer_id
               OR OLD.payment_type IS DISTINCT FROM NEW.payment_type
               OR OLD.total_amount IS DISTINCT FROM NEW.total_amount
               OR OLD.customer_name_snapshot IS DISTINCT FROM NEW.customer_name_snapshot
               OR OLD.customer_gstin_snapshot IS DISTINCT FROM NEW.customer_gstin_snapshot
               OR OLD.billing_address_snapshot IS DISTINCT FROM NEW.billing_address_snapshot
               OR OLD.shipping_address_snapshot IS DISTINCT FROM NEW.shipping_address_snapshot
               OR OLD.state_snapshot IS DISTINCT FROM NEW.state_snapshot
               OR OLD.pincode_snapshot IS DISTINCT FROM NEW.pincode_snapshot
               OR (OLD.state = 'CANCELLED' AND NEW.state <> 'CANCELLED')
               OR (OLD.state = 'POSTED' AND NEW.state NOT IN ('POSTED', 'CANCELLED'))
            THEN
                RAISE EXCEPTION 'Posted and cancelled invoice financial data is immutable';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_invoicelineitem' THEN
        SELECT state INTO invoice_state FROM billing_invoice WHERE id = OLD.invoice_id;
        IF TG_OP = 'DELETE' AND invoice_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled invoice lines cannot be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND invoice_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled invoice lines are immutable';
        END IF;
    ELSIF TG_TABLE_NAME IN ('billing_payment', 'billing_paymentreversal', 'billing_creditnote', 'billing_creditnotelineitem', 'billing_auditlog', 'billing_debitnote', 'inventory_stockledger') THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
        END IF;
    ELSIF TG_TABLE_NAME = 'inventory_inventorybalance' THEN
        IF TG_OP IN ('UPDATE', 'DELETE') AND current_setting('stockbill.allow_inventory_mutation', true) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'InventoryBalance changes must use inventory services';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
'''

TABLES = [
    "billing_invoice",
    "billing_invoicelineitem",
    "billing_payment",
    "billing_paymentreversal",
    "billing_creditnote",
    "billing_creditnotelineitem",
    "billing_auditlog",
    "billing_debitnote",
    "inventory_stockledger",
    "inventory_inventorybalance",
]


def forwards(apps, schema_editor):
    schema_editor.execute(TRIGGER_FUNCTION)
    for table in TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER stockbill_protect_{table} "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION stockbill_protect_history();"
        )


def backwards(apps, schema_editor):
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS stockbill_protect_{table} ON {table};")
    schema_editor.execute("DROP FUNCTION IF EXISTS stockbill_protect_history();")


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0007_invoiceidempotencykey_request_hash"),
        ("inventory", "0006_alter_stockledger_movement_type"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
