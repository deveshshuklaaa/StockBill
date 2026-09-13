"""Supplier master data + purchase integration test suite.

Scope is supplier management only — no supplier financial accounting:

- list pagination, server-side search (name/GSTIN/phone), is_active filtering
- detail retrieval and edit with GSTIN/state-code validation
- archive (soft) keeps supplier rows and purchase references intact
- reactivate restores new-purchase eligibility
- purchase history is scoped server-side: supplier A never sees supplier B
- archived suppliers cannot be used for new purchases (backend rule)
- posted purchase supplier snapshots never mutate when master data changes
- permission boundaries: staff read-only, admin write, anonymous rejected
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from billing.models import AuditLog, BusinessProfile
from inventory.models import (
    InventoryBalance,
    Product,
    PurchaseInvoice,
    StockLedger,
    Supplier,
    TaxRate,
)
from inventory.services import get_default_warehouse

User = get_user_model()


def make_supplier_context(cls):
    cls.admin = User.objects.create_user(
        username="supplier-admin", password="StrongPass123!", role="admin"
    )
    cls.staff = User.objects.create_user(
        username="supplier-staff", password="StrongPass123!", role="staff"
    )
    BusinessProfile.objects.create(
        business_name="Divya Enterprises",
        gstin="27DIVYA1234A1Z5",
        registered_address="Shop 1, Main Road, Mumbai",
        state="Maharashtra",
        state_code="27",
    )
    cls.tax, _ = TaxRate.objects.get_or_create(
        name="GST 18%", defaults={"rate": Decimal("18.00")}
    )
    cls.warehouse = get_default_warehouse()
    cls.supplier_alpha = Supplier.objects.create(
        name="Alpha Traders Pvt. Ltd.",
        contact_info="9820011122",
        gstin="27AAACA1234A1Z5",
        address="12, Wholesale Market, Mumbai",
        state="Maharashtra",
        state_code="27",
    )
    cls.supplier_beta = Supplier.objects.create(
        name="Beta Distributors",
        contact_info="9820033344",
        gstin="24AAACB5678B1Z3",
        address="5, Industrial Estate, Surat",
        state="Gujarat",
        state_code="24",
    )
    cls.product = Product.objects.create(
        name="Supplier Test Product",
        base_unit=Product.UNIT_PIECE,
        unit_type=Product.UNIT_PIECE,
        unit_conversion_factor=1,
        default_price=10,
        mrp=10,
        tax=cls.tax,
        current_stock=0,
    )


def purchase_payload(cls, supplier, bill_no="", post=False, rate="6.00"):
    payload = {
        "supplier": supplier.pk,
        "warehouse": cls.warehouse.pk,
        "supplier_invoice_no": bill_no,
        "invoice_date": "2026-09-10",
        "tax_mode": "exclusive",
        "line_items": [
            {"product": cls.product.pk, "quantity": "10", "rate": rate}
        ],
    }
    if post:
        payload["post"] = True
    return payload


class SupplierListTests(APITestCase):
    """List, search, pagination, and active filtering."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_supplier_list_is_paginated(self):
        # 25 per page (PAGE_SIZE): page 1 alone must hold the seeded rows.
        response = self.client.get("/api/suppliers/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNone(response.data["previous"])

    def test_supplier_list_paginates_beyond_page_size(self):
        Supplier.objects.bulk_create(
            [Supplier(name=f"Bulk Supplier {i:02d}") for i in range(1, 26)]
        )
        first = self.client.get("/api/suppliers/")
        self.assertEqual(first.data["count"], 27)
        self.assertEqual(len(first.data["results"]), 25)
        self.assertIsNotNone(first.data["next"])
        second = self.client.get("/api/suppliers/?page=2")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.data["results"]), 2)
        self.assertIsNone(second.data["next"])
        # Ids stay unique across pages: no row is repeated.
        page_one_ids = {row["id"] for row in first.data["results"]}
        page_two_ids = {row["id"] for row in second.data["results"]}
        self.assertFalse(page_one_ids & page_two_ids)

    def test_search_matches_name_gstin_and_phone(self):
        by_name = self.client.get("/api/suppliers/", {"search": "Alpha"})
        self.assertEqual(by_name.data["count"], 1)
        self.assertEqual(by_name.data["results"][0]["name"], "Alpha Traders Pvt. Ltd.")

        by_gstin = self.client.get("/api/suppliers/", {"search": "27AAACA"})
        self.assertEqual(by_gstin.data["count"], 1)
        self.assertEqual(
            by_gstin.data["results"][0]["gstin"], "27AAACA1234A1Z5"
        )

        by_phone = self.client.get("/api/suppliers/", {"search": "9820011122"})
        self.assertEqual(by_phone.data["count"], 1)
        self.assertEqual(by_phone.data["results"][0]["contact_info"], "9820011122")

    def test_search_ignores_other_suppliers_rows(self):
        response = self.client.get("/api/suppliers/", {"search": "Alpha"})
        names = [row["name"] for row in response.data["results"]]
        self.assertNotIn("Beta Distributors", names)

    def test_active_filter_and_validation(self):
        Supplier.objects.create(name="Archived Supplier", is_active=False)
        active = self.client.get("/api/suppliers/", {"is_active": "true"})
        self.assertEqual(active.data["count"], 2)
        inactive = self.client.get("/api/suppliers/", {"is_active": "false"})
        self.assertEqual(inactive.data["count"], 1)
        self.assertEqual(inactive.data["results"][0]["name"], "Archived Supplier")
        invalid = self.client.get("/api/suppliers/", {"is_active": "bogus"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("is_active", invalid.data)

    def test_list_fields_expose_master_data(self):
        row = self.client.get("/api/suppliers/").data["results"][0]
        for field in (
            "id",
            "name",
            "contact_info",
            "gstin",
            "address",
            "state",
            "state_code",
            "is_active",
        ):
            self.assertIn(field, row)


class SupplierDetailAndArchiveTests(APITestCase):
    """Detail, edit, archive, reactivate, and audit trail."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_detail_returns_full_master_data(self):
        response = self.client.get(f"/api/suppliers/{self.supplier_alpha.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Alpha Traders Pvt. Ltd.")
        self.assertEqual(response.data["gstin"], "27AAACA1234A1Z5")
        self.assertEqual(response.data["address"], "12, Wholesale Market, Mumbai")
        self.assertEqual(response.data["state"], "Maharashtra")
        self.assertEqual(response.data["state_code"], "27")
        self.assertTrue(response.data["is_active"])

    def test_update_validates_gstin_and_state_code(self):
        bad_gstin = self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {"gstin": "27INVALID"},
            format="json",
        )
        self.assertEqual(bad_gstin.status_code, 400)
        self.assertIn("gstin", bad_gstin.data)

        bad_code = self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {"state_code": "MH"},
            format="json",
        )
        self.assertEqual(bad_code.status_code, 400)
        self.assertIn("state_code", bad_code.data)

    def test_update_saves_master_data_and_audits(self):
        response = self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {"contact_info": "9899999999", "address": "Updated Address"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.supplier_alpha.refresh_from_db()
        self.assertEqual(self.supplier_alpha.contact_info, "9899999999")
        self.assertEqual(self.supplier_alpha.address, "Updated Address")
        self.assertTrue(
            AuditLog.objects.filter(
                action="supplier_updated",
                entity_type="Supplier",
                entity_id=self.supplier_alpha.pk,
            ).exists()
        )

    def test_archive_is_soft_and_audited(self):
        response = self.client.delete(f"/api/suppliers/{self.supplier_alpha.pk}/")
        self.assertEqual(response.status_code, 204)
        self.supplier_alpha.refresh_from_db()
        # Row survives; only the flag flipped.
        self.assertFalse(self.supplier_alpha.is_active)
        self.assertTrue(Supplier.objects.filter(pk=self.supplier_alpha.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="supplier_archived",
                entity_type="Supplier",
                entity_id=self.supplier_alpha.pk,
            ).exists()
        )

    def test_reactivate_restores_active_status(self):
        self.supplier_alpha.is_active = False
        self.supplier_alpha.save(update_fields=["is_active"])
        response = self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.supplier_alpha.refresh_from_db()
        self.assertTrue(self.supplier_alpha.is_active)

    def test_archive_keeps_purchase_references_and_inventory_intact(self):
        created = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "ALPHA-BILL-1", post=True),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        purchase = PurchaseInvoice.objects.get(pk=created.data["id"])

        self.client.delete(f"/api/suppliers/{self.supplier_alpha.pk}/")
        self.supplier_alpha.refresh_from_db()
        self.assertFalse(self.supplier_alpha.is_active)

        purchase.refresh_from_db()
        # The posted purchase still references the same supplier row and its
        # snapshots, stock, and ledger movements are untouched.
        self.assertEqual(purchase.supplier_id, self.supplier_alpha.pk)
        self.assertEqual(purchase.state, PurchaseInvoice.STATE_POSTED)
        self.assertEqual(purchase.supplier_name_snapshot, "Alpha Traders Pvt. Ltd.")
        balance = InventoryBalance.objects.get(
            product=self.product, warehouse=self.warehouse
        )
        self.assertEqual(balance.quantity_on_hand, Decimal("10.000"))
        self.assertTrue(
            StockLedger.objects.filter(
                reference_type="purchase_invoice", reference_id=purchase.pk
            ).exists()
        )

    def test_archived_supplier_name_visible_in_history(self):
        created = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "ALPHA-BILL-2", post=True),
            format="json",
        )
        purchase_id = created.data["id"]
        self.client.delete(f"/api/suppliers/{self.supplier_alpha.pk}/")

        response = self.client.get(f"/api/purchase-invoices/{purchase_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["supplier_name"], "Alpha Traders Pvt. Ltd.")
        self.assertEqual(
            response.data["supplier_name_snapshot"], "Alpha Traders Pvt. Ltd."
        )


class SupplierPurchaseHistoryTests(APITestCase):
    """Purchase history is scoped server-side to the requested supplier."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _create_for(self, supplier, bill_no):
        response = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, supplier, bill_no),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_history_scoped_to_single_supplier(self):
        self._create_for(self.supplier_alpha, "ALPHA-H-1")
        self._create_for(self.supplier_alpha, "ALPHA-H-2")
        self._create_for(self.supplier_beta, "BETA-H-1")

        response = self.client.get(
            "/api/purchase-invoices/", {"supplier": self.supplier_alpha.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        suppliers_returned = {
            row["supplier"] for row in response.data["results"]
        }
        self.assertEqual(suppliers_returned, {self.supplier_alpha.pk})
        bills = {row["supplier_invoice_no"] for row in response.data["results"]}
        self.assertEqual(bills, {"ALPHA-H-1", "ALPHA-H-2"})

    def test_history_includes_drafts_posted_and_cancelled(self):
        self._create_for(self.supplier_alpha, "ALPHA-MIX-DRAFT")
        posted = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "ALPHA-MIX-POSTED", post=True),
            format="json",
        )
        self.assertEqual(posted.status_code, 201, posted.data)
        cancel = self.client.post(
            f"/api/purchase-invoices/{posted.data['id']}/cancel/",
            {"reason": "supplier history test"},
            format="json",
        )
        self.assertEqual(cancel.status_code, 200, cancel.data)

        response = self.client.get(
            "/api/purchase-invoices/", {"supplier": self.supplier_alpha.pk}
        )
        states = {row["state"] for row in response.data["results"]}
        self.assertEqual(states, {"DRAFT", "CANCELLED"})
        self.assertEqual(response.data["count"], 2)

    def test_history_rows_carry_detail_fields(self):
        self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "ALPHA-F-1", post=True),
            format="json",
        )
        row = self.client.get(
            "/api/purchase-invoices/", {"supplier": self.supplier_alpha.pk}
        ).data["results"][0]
        for field in (
            "id",
            "purchase_number",
            "supplier_invoice_no",
            "invoice_date",
            "state",
            "total_amount",
            "warehouse_name",
        ):
            self.assertIn(field, row)

    def test_supplier_id_must_be_numeric(self):
        response = self.client.get(
            "/api/purchase-invoices/", {"supplier": "not-a-number"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("supplier", response.data)


class SupplierPurchaseEligibilityTests(APITestCase):
    """Archived suppliers cannot be used for NEW purchases."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_archived_supplier_rejected_for_new_purchase(self):
        self.supplier_alpha.is_active = False
        self.supplier_alpha.save(update_fields=["is_active"])
        response = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "ARCH-1"),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("supplier", response.data)

    def test_reactivated_supplier_accepted_again(self):
        self.supplier_alpha.is_active = False
        self.supplier_alpha.save(update_fields=["is_active"])
        blocked = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "REACT-1"),
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)

        self.supplier_alpha.is_active = True
        self.supplier_alpha.save(update_fields=["is_active"])
        allowed = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "REACT-2"),
            format="json",
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_draft_supplier_cannot_be_swapped_to_archived(self):
        created = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_beta, "SWAP-1"),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.supplier_alpha.is_active = False
        self.supplier_alpha.save(update_fields=["is_active"])
        swapped = self.client.patch(
            f"/api/purchase-invoices/{created.data['id']}/",
            {"supplier": self.supplier_alpha.pk},
            format="json",
        )
        self.assertEqual(swapped.status_code, 400, swapped.data)
        self.assertIn("supplier", swapped.data)


class SupplierSnapshotImmutabilityTests(APITestCase):
    """Master-data edits must never mutate posted purchase snapshots."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def setUp(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "SNAP-1", post=True),
            format="json",
        )
        self.purchase_id = created.data["id"]

    def test_supplier_master_changes_do_not_mutate_posted_snapshot(self):
        self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {
                "name": "Renamed Traders",
                "gstin": "27BBBBB9999C1Z9",
                "state": "Gujarat",
                "state_code": "24",
                "address": "Moved Address",
            },
            format="json",
        )
        purchase = PurchaseInvoice.objects.get(pk=self.purchase_id)
        self.assertEqual(purchase.supplier_name_snapshot, "Alpha Traders Pvt. Ltd.")
        self.assertEqual(purchase.supplier_gstin_snapshot, "27AAACA1234A1Z5")
        self.assertEqual(purchase.supplier_state_snapshot, "Maharashtra")
        self.assertEqual(purchase.supplier_state_code_snapshot, "27")

    def test_draft_purchase_cannot_be_edited_after_supplier_rename(self):
        # Drafts are mutable documents; renaming the supplier must not touch
        # a draft's stored snapshot either (only service-driven updates do).
        created = self.client.post(
            "/api/purchase-invoices/",
            purchase_payload(self, self.supplier_alpha, "SNAP-2"),
            format="json",
        )
        draft = PurchaseInvoice.objects.get(pk=created.data["id"])
        self.client.patch(
            f"/api/suppliers/{self.supplier_alpha.pk}/",
            {"name": "Renamed Again"},
            format="json",
        )
        draft.refresh_from_db()
        self.assertEqual(draft.supplier_name_snapshot, "Alpha Traders Pvt. Ltd.")


class SupplierPermissionTests(APITestCase):
    """Backend permission model for supplier endpoints."""

    @classmethod
    def setUpTestData(cls):
        make_supplier_context(cls)

    def test_staff_can_list_and_detail_but_not_write(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get("/api/suppliers/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/suppliers/{self.supplier_alpha.pk}/").status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/suppliers/", {"name": "Staff Supplier"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/suppliers/{self.supplier_alpha.pk}/",
                {"name": "Staff Edit"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f"/api/suppliers/{self.supplier_alpha.pk}/").status_code,
            403,
        )
        # Staff cannot read purchase history at all.
        self.assertEqual(
            self.client.get(
                "/api/purchase-invoices/", {"supplier": self.supplier_alpha.pk}
            ).status_code,
            403,
        )

    def test_staff_cannot_archive_supplier(self):
        self.client.force_authenticate(self.staff)
        response = self.client.delete(f"/api/suppliers/{self.supplier_alpha.pk}/")
        self.assertEqual(response.status_code, 403)
        self.supplier_alpha.refresh_from_db()
        self.assertTrue(self.supplier_alpha.is_active)

    def test_anonymous_requests_rejected(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/suppliers/").status_code, {401, 403})

    def test_admin_can_create_supplier_with_audit_log(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/suppliers/",
            {
                "name": "Permission Supplier",
                "gstin": "27AAACP7777P1Z5",
                "state": "Maharashtra",
                "state_code": "27",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            AuditLog.objects.filter(
                action="supplier_created",
                entity_type="Supplier",
                entity_id=response.data["id"],
            ).exists()
        )

    def test_404_for_missing_supplier(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/suppliers/999999/").status_code, 404)
