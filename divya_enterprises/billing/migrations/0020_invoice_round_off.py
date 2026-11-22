"""Optional round-off of the invoice total (Release A).

* BusinessProfile.round_off_invoice_total (default True: the shop profile
  gets True, as decided by the business).
* Invoice.round_off and CreditNote.round_off, default 0.00. Existing rows
  keep 0.00 and their totals: AddField with a default writes no UPDATE, so
  no posted invoice is touched.
* stockbill_protect_history(): the body is copied verbatim from the latest
  redefinition, inventory/0016 (which itself followed billing/0019), plus
  Invoice.round_off in the POSTED/CANCELLED invoice check. CreditNote rows
  are already append-only, so CreditNote.round_off needs no extra rule.
  Backwards restores the inventory/0016 body exactly.
"""

from decimal import Decimal

from django.db import migrations, models

# Body as installed by inventory/0016 (restored on reverse).
PREVIOUS_TRIGGER_FUNCTION = r'''
CREATE OR REPLACE FUNCTION stockbill_protect_history() RETURNS trigger AS $$
DECLARE
    invoice_state text;
    purchase_state text;
BEGIN
    IF TG_TABLE_NAME = 'billing_invoice' THEN
        IF TG_OP = 'DELETE' AND OLD.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Only draft invoices can be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.state IN ('POSTED', 'CANCELLED') THEN
            IF OLD.invoice_number IS DISTINCT FROM NEW.invoice_number
               OR OLD.invoice_date IS DISTINCT FROM NEW.invoice_date
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
    ELSIF TG_TABLE_NAME = 'inventory_purchaseinvoice' THEN
        IF TG_OP = 'DELETE' AND OLD.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Only draft purchases can be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.state IN ('POSTED', 'CANCELLED') THEN
            IF OLD.supplier_id IS DISTINCT FROM NEW.supplier_id
               OR OLD.warehouse_id IS DISTINCT FROM NEW.warehouse_id
               OR OLD.purchase_number IS DISTINCT FROM NEW.purchase_number
               OR OLD.supplier_invoice_no IS DISTINCT FROM NEW.supplier_invoice_no
               OR OLD.invoice_date IS DISTINCT FROM NEW.invoice_date
               OR OLD.tax_mode IS DISTINCT FROM NEW.tax_mode
               OR OLD.supplier_name_snapshot IS DISTINCT FROM NEW.supplier_name_snapshot
               OR OLD.supplier_gstin_snapshot IS DISTINCT FROM NEW.supplier_gstin_snapshot
               OR OLD.supplier_state_snapshot IS DISTINCT FROM NEW.supplier_state_snapshot
               OR OLD.supplier_state_code_snapshot IS DISTINCT FROM NEW.supplier_state_code_snapshot
               OR OLD.subtotal IS DISTINCT FROM NEW.subtotal
               OR OLD.discount_total IS DISTINCT FROM NEW.discount_total
               OR OLD.taxable_total IS DISTINCT FROM NEW.taxable_total
               OR OLD.cgst_total IS DISTINCT FROM NEW.cgst_total
               OR OLD.sgst_total IS DISTINCT FROM NEW.sgst_total
               OR OLD.igst_total IS DISTINCT FROM NEW.igst_total
               OR OLD.total_amount IS DISTINCT FROM NEW.total_amount
               OR OLD.posted_at IS DISTINCT FROM NEW.posted_at
               OR (OLD.state = 'CANCELLED' AND NEW.state <> 'CANCELLED')
               OR (OLD.state = 'POSTED' AND NEW.state NOT IN ('POSTED', 'CANCELLED'))
            THEN
                RAISE EXCEPTION 'Posted and cancelled purchase financial data is immutable';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'inventory_purchaselineitem' THEN
        SELECT state INTO purchase_state FROM inventory_purchaseinvoice WHERE id = OLD.purchase_invoice_id;
        IF TG_OP = 'DELETE' AND purchase_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled purchase lines cannot be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND purchase_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled purchase lines are immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'inventory_purchaseidempotencykey' THEN
        -- Append-only, except a draft purchase's key may be removed together
        -- with that draft (delete_purchase). Keys of posted/cancelled
        -- purchases can never be changed or deleted.
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
        END IF;
        IF TG_OP = 'DELETE' THEN
            SELECT state INTO purchase_state FROM inventory_purchaseinvoice WHERE id = OLD.purchase_id;
            IF purchase_state IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'Only draft purchase idempotency keys can be deleted';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'billing_payment', 'billing_paymentreversal', 'billing_creditnote',
        'billing_creditnotelineitem', 'billing_auditlog', 'billing_debitnote',
        'inventory_stockledger',
        'inventory_stockadjustment', 'inventory_stockadjustmentidempotencykey',
        'inventory_openingstock', 'inventory_openingstockidempotencykey'
    ) THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'inventory_purchasenumbercounter', 'inventory_stockadjustmentnumbercounter',
        'inventory_openingstocknumbercounter',
        'billing_invoicenumbercounter', 'billing_creditnotenumbercounter'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '%% rows cannot be deleted', TG_TABLE_NAME;
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

TRIGGER_FUNCTION = r'''
CREATE OR REPLACE FUNCTION stockbill_protect_history() RETURNS trigger AS $$
DECLARE
    invoice_state text;
    purchase_state text;
BEGIN
    IF TG_TABLE_NAME = 'billing_invoice' THEN
        IF TG_OP = 'DELETE' AND OLD.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Only draft invoices can be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.state IN ('POSTED', 'CANCELLED') THEN
            IF OLD.invoice_number IS DISTINCT FROM NEW.invoice_number
               OR OLD.invoice_date IS DISTINCT FROM NEW.invoice_date
               OR OLD.customer_id IS DISTINCT FROM NEW.customer_id
               OR OLD.payment_type IS DISTINCT FROM NEW.payment_type
               OR OLD.total_amount IS DISTINCT FROM NEW.total_amount
               OR OLD.round_off IS DISTINCT FROM NEW.round_off
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
    ELSIF TG_TABLE_NAME = 'inventory_purchaseinvoice' THEN
        IF TG_OP = 'DELETE' AND OLD.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Only draft purchases can be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.state IN ('POSTED', 'CANCELLED') THEN
            IF OLD.supplier_id IS DISTINCT FROM NEW.supplier_id
               OR OLD.warehouse_id IS DISTINCT FROM NEW.warehouse_id
               OR OLD.purchase_number IS DISTINCT FROM NEW.purchase_number
               OR OLD.supplier_invoice_no IS DISTINCT FROM NEW.supplier_invoice_no
               OR OLD.invoice_date IS DISTINCT FROM NEW.invoice_date
               OR OLD.tax_mode IS DISTINCT FROM NEW.tax_mode
               OR OLD.supplier_name_snapshot IS DISTINCT FROM NEW.supplier_name_snapshot
               OR OLD.supplier_gstin_snapshot IS DISTINCT FROM NEW.supplier_gstin_snapshot
               OR OLD.supplier_state_snapshot IS DISTINCT FROM NEW.supplier_state_snapshot
               OR OLD.supplier_state_code_snapshot IS DISTINCT FROM NEW.supplier_state_code_snapshot
               OR OLD.subtotal IS DISTINCT FROM NEW.subtotal
               OR OLD.discount_total IS DISTINCT FROM NEW.discount_total
               OR OLD.taxable_total IS DISTINCT FROM NEW.taxable_total
               OR OLD.cgst_total IS DISTINCT FROM NEW.cgst_total
               OR OLD.sgst_total IS DISTINCT FROM NEW.sgst_total
               OR OLD.igst_total IS DISTINCT FROM NEW.igst_total
               OR OLD.total_amount IS DISTINCT FROM NEW.total_amount
               OR OLD.posted_at IS DISTINCT FROM NEW.posted_at
               OR (OLD.state = 'CANCELLED' AND NEW.state <> 'CANCELLED')
               OR (OLD.state = 'POSTED' AND NEW.state NOT IN ('POSTED', 'CANCELLED'))
            THEN
                RAISE EXCEPTION 'Posted and cancelled purchase financial data is immutable';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'inventory_purchaselineitem' THEN
        SELECT state INTO purchase_state FROM inventory_purchaseinvoice WHERE id = OLD.purchase_invoice_id;
        IF TG_OP = 'DELETE' AND purchase_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled purchase lines cannot be deleted';
        END IF;
        IF TG_OP = 'UPDATE' AND purchase_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted and cancelled purchase lines are immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'inventory_purchaseidempotencykey' THEN
        -- Append-only, except a draft purchase's key may be removed together
        -- with that draft (delete_purchase). Keys of posted/cancelled
        -- purchases can never be changed or deleted.
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
        END IF;
        IF TG_OP = 'DELETE' THEN
            SELECT state INTO purchase_state FROM inventory_purchaseinvoice WHERE id = OLD.purchase_id;
            IF purchase_state IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'Only draft purchase idempotency keys can be deleted';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'billing_payment', 'billing_paymentreversal', 'billing_creditnote',
        'billing_creditnotelineitem', 'billing_auditlog', 'billing_debitnote',
        'inventory_stockledger',
        'inventory_stockadjustment', 'inventory_stockadjustmentidempotencykey',
        'inventory_openingstock', 'inventory_openingstockidempotencykey'
    ) THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            RAISE EXCEPTION '%% rows are append-only', TG_TABLE_NAME;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'inventory_purchasenumbercounter', 'inventory_stockadjustmentnumbercounter',
        'inventory_openingstocknumbercounter',
        'billing_invoicenumbercounter', 'billing_creditnotenumbercounter'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '%% rows cannot be deleted', TG_TABLE_NAME;
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


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(TRIGGER_FUNCTION)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(PREVIOUS_TRIGGER_FUNCTION)


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0019_creditnote_number_required_invoice_date_immutable"),
        # Must run after the latest redefinition of stockbill_protect_history().
        ("inventory", "0016_allow_draft_purchase_idempotency_key_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessprofile",
            name="round_off_invoice_total",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="creditnote",
            name="round_off",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6),
        ),
        migrations.AddField(
            model_name="invoice",
            name="round_off",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6),
        ),
        migrations.RunPython(install, uninstall),
    ]
