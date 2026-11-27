"""Release B2: the shop logo is uploaded, validated, stored in the database
and printed on invoices."""

import importlib
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from PIL import Image
from rest_framework.test import APIClient, APITestCase

from billing.logo import MAX_SIDE, LogoError, normalize_logo
from billing.models import AuditLog, BusinessProfile, Invoice
from billing.pdf_engine import build_invoice_a5_pdf

User = get_user_model()
MIGRATION = importlib.import_module("billing.migrations.0023_businessprofile_logo")


def image_bytes(fmt, size=(1200, 800), mode="RGB", color=(15, 94, 87), **save_kwargs):
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def decoded(png):
    image = Image.open(BytesIO(png))
    image.load()
    return image


class NormalizeLogoTests(TestCase):
    def test_png_is_scaled_and_stored_as_png(self):
        image = decoded(normalize_logo(image_bytes("PNG", (1200, 800), "RGBA", (15, 94, 87, 128))))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.size, (600, 400))
        self.assertEqual(image.mode, "RGBA")  # transparency kept

    def test_jpeg_is_converted_to_png(self):
        image = decoded(normalize_logo(image_bytes("JPEG", (900, 300))))
        self.assertEqual((image.format, image.size, image.mode), ("PNG", (600, 200), "RGB"))

    def test_small_image_is_not_enlarged(self):
        self.assertEqual(decoded(normalize_logo(image_bytes("PNG", (120, 80)))).size, (120, 80))

    def test_exif_orientation_is_applied_and_metadata_dropped(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees clockwise on display
        exif[0x010F] = "SecretCam"  # camera make: must not survive
        raw = image_bytes("JPEG", (400, 200), exif=exif.tobytes())
        image = decoded(normalize_logo(raw))
        self.assertEqual(image.size, (200, 400))
        self.assertFalse(dict(image.getexif()))
        self.assertNotIn(b"SecretCam", normalize_logo(raw))

    def test_rejects_svg(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
        with self.assertRaisesMessage(LogoError, "PNG or JPEG"):
            normalize_logo(svg)

    def test_rejects_renamed_text_file(self):
        with self.assertRaisesMessage(LogoError, "PNG or JPEG"):
            normalize_logo(b"this is not an image, just text renamed to logo.png")

    def test_rejects_gif_and_webp_by_decoded_format(self):
        for fmt in ("GIF", "WEBP"):
            with self.subTest(fmt=fmt), self.assertRaisesMessage(LogoError, f"this file is {fmt}"):
                normalize_logo(image_bytes(fmt, (50, 50)))

    def test_rejects_more_than_two_megabytes(self):
        with self.assertRaisesMessage(LogoError, "2 MB or smaller"):
            normalize_logo(os.urandom(2 * 1024 * 1024 + 1))

    def test_rejects_decompression_bomb(self):
        bomb = image_bytes("PNG", (6000, 5000), "1", 0)  # 30 MP of black: a tiny file
        self.assertLess(len(bomb), 200_000)
        with self.assertRaisesMessage(LogoError, "too large to process"):
            normalize_logo(bomb)

    def test_rejects_empty_and_damaged_files(self):
        with self.assertRaises(LogoError):
            normalize_logo(b"")
        with self.assertRaises(LogoError):
            normalize_logo(image_bytes("PNG", (300, 300))[:200])


class LogoEndpointTests(APITestCase):
    URL = "/api/business-profile/logo/"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="logo-admin", password="Pass-12345!", role="admin")
        cls.staff = User.objects.create_user(username="logo-staff", password="Pass-12345!", role="staff")
        BusinessProfile.objects.create(business_name="Sharma General Store", gstin="27AAAAA0000A1Z5",
                                       registered_address="Pune", state="Maharashtra", state_code="27")

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def upload(self, user, data, name="logo.png", content_type="image/png"):
        return self.client_for(user).post(self.URL, {"logo": SimpleUploadedFile(name, data, content_type=content_type)},
                                          format="multipart")

    def test_admin_uploads_png_and_staff_can_view_it(self):
        response = self.upload(self.admin, image_bytes("PNG", (1500, 500)))
        self.assertEqual(response.status_code, 201, response.content)
        profile = BusinessProfile.objects.get()
        self.assertEqual(profile.logo_content_type, "image/png")
        self.assertEqual(decoded(bytes(profile.logo)).size, (MAX_SIDE, 200))
        view = self.client_for(self.staff).get(self.URL)
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view["Content-Type"], "image/png")
        self.assertEqual(view.content, bytes(profile.logo))
        self.assertTrue(AuditLog.objects.filter(action="business_logo_uploaded").exists())
        self.assertTrue(self.client_for(self.admin).get("/api/business-profile/").data["has_logo"])

    def test_admin_uploads_jpeg_named_png_by_content(self):
        response = self.upload(self.admin, image_bytes("JPEG", (300, 300)), name="photo.jpg", content_type="image/jpeg")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(decoded(bytes(BusinessProfile.objects.get().logo)).format, "PNG")

    def test_rejections_show_a_clear_message(self):
        cases = [
            ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "PNG or JPEG"),
            ("logo.png", b"plain text renamed", "image/png", "PNG or JPEG"),  # extension and type lie
            ("logo.gif", image_bytes("GIF", (40, 40)), "image/gif", "GIF"),
            ("logo.png", os.urandom(2 * 1024 * 1024 + 10), "image/png", "2 MB"),
            ("logo.png", image_bytes("PNG", (6000, 5000), "1", 0), "image/png", "too large to process"),
        ]
        for name, data, content_type, message in cases:
            with self.subTest(name=name, message=message):
                response = self.upload(self.admin, data, name=name, content_type=content_type)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.data["logo"][0])
        self.assertFalse(BusinessProfile.objects.get().logo)

    def test_missing_file_is_a_validation_error(self):
        response = self.client_for(self.admin).post(self.URL, {}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_staff_cannot_upload_or_delete(self):
        self.assertEqual(self.upload(self.staff, image_bytes("PNG", (50, 50))).status_code, 403)
        self.assertEqual(self.client_for(self.staff).delete(self.URL).status_code, 403)

    def test_anonymous_cannot_view(self):
        self.assertIn(APIClient().get(self.URL).status_code, (401, 403))

    def test_delete_removes_the_logo(self):
        self.upload(self.admin, image_bytes("PNG", (50, 50)))
        self.assertEqual(self.client_for(self.admin).delete(self.URL).status_code, 204)
        profile = BusinessProfile.objects.get()
        self.assertFalse(profile.logo)
        self.assertEqual(self.client_for(self.staff).get(self.URL).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action="business_logo_removed").exists())
        self.assertFalse(self.client_for(self.admin).get("/api/business-profile/").data["has_logo"])


class LogoOnPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.profile = BusinessProfile.objects.create(business_name="Sharma General Store", gstin="27AAAAA0000A1Z5",
                                                     registered_address="Pune", state="Maharashtra", state_code="27")

    def render(self):
        invoice = Invoice(invoice_number="DE/26-27/00001", state=Invoice.STATE_POSTED, place_of_supply="27",
                          seller_business_name_snapshot="Sharma General Store", seller_address_snapshot="Pune",
                          seller_gstin_snapshot="27AAAAA0000A1Z5", seller_state_snapshot="Maharashtra",
                          seller_state_code_snapshot="27")
        return pymupdf.open("pdf", build_invoice_a5_pdf(invoice, lines=[]))[0]

    def seller_name_x(self, page):
        return next(w for w in page.get_text("words") if w[4] == "SHARMA")[0]

    def test_pdf_prints_the_uploaded_logo(self):
        BusinessProfile.objects.filter(pk=self.profile.pk).update(logo=normalize_logo(image_bytes("PNG", (300, 300))),
                                                                  logo_content_type="image/png")
        page = self.render()
        self.assertEqual(len(page.get_images()), 1)
        self.assertGreater(self.seller_name_x(page), 60)  # text starts after the logo

    def test_pdf_without_logo_has_no_image_and_text_starts_at_the_left(self):
        page = self.render()
        self.assertEqual(page.get_images(), [])
        self.assertLess(self.seller_name_x(page), 40)

    def test_damaged_stored_logo_does_not_break_the_pdf(self):
        BusinessProfile.objects.filter(pk=self.profile.pk).update(logo=b"not an image", logo_content_type="image/png")
        with self.assertLogs("billing.pdf_engine", level="WARNING"):
            page = self.render()
        self.assertEqual(page.get_images(), [])


class LegacyLogoMigrationFunctionTests(TestCase):
    """The data step of migration 0021, run directly against current models."""

    def run_step(self):
        MIGRATION.load_legacy_logo(global_apps, None)

    def test_loads_logo_jpg_into_an_existing_empty_profile(self):
        self.assertTrue(Path(MIGRATION.LEGACY_LOGO_PATH).is_file())
        BusinessProfile.objects.create(business_name="Shop", gstin="G", registered_address="A", state="S", state_code="27")
        self.run_step()
        profile = BusinessProfile.objects.get()
        image = decoded(bytes(profile.logo))
        self.assertEqual((image.format, max(image.size)), ("PNG", MAX_SIDE))
        self.assertEqual(profile.logo_content_type, "image/png")
        self.assertIsNotNone(profile.logo_updated_at)

    def test_keeps_an_existing_logo(self):
        existing = normalize_logo(image_bytes("PNG", (40, 40)))
        BusinessProfile.objects.create(business_name="Shop", gstin="G", registered_address="A", state="S", state_code="27",
                                       logo=existing, logo_content_type="image/png")
        self.run_step()
        self.assertEqual(bytes(BusinessProfile.objects.get().logo), existing)

    def test_no_profile_is_a_no_op(self):
        self.run_step()
        self.assertFalse(BusinessProfile.objects.exists())

    def test_missing_file_is_a_no_op(self):
        BusinessProfile.objects.create(business_name="Shop", gstin="G", registered_address="A", state="S", state_code="27")
        with patch.object(MIGRATION, "LEGACY_LOGO_PATH", Path("does/not/exist/logo.jpg")):
            self.run_step()
        self.assertFalse(BusinessProfile.objects.get().logo)


class LogoMigrationTests(TransactionTestCase):
    """Migration 0023 end to end, and its reversal."""

    before = [("billing", "0022_creditnote_destination_warehouse")]
    after = [("billing", "0023_businessprofile_logo")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_profile_gets_the_logo_and_migration_reverses(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        Profile20 = executor.loader.project_state(self.before).apps.get_model("billing", "BusinessProfile")  # noqa: N806
        Profile20.objects.create(business_name="Shop", gstin="G", registered_address="A", state="S", state_code="27")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        Profile21 = executor.loader.project_state(self.after).apps.get_model("billing", "BusinessProfile")  # noqa: N806
        self.assertEqual(decoded(bytes(Profile21.objects.get().logo)).format, "PNG")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.before)
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'billing_businessprofile'")
            columns = {row[0] for row in cursor.fetchall()}
        self.assertNotIn("logo", columns)
