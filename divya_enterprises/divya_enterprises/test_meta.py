"""Release A2: GET /api/meta/ tells the frontend which installation this is."""

import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token


class MetaEndpointTests(SimpleTestCase):
    def get(self):
        response = self.client.get("/api/meta/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-cache", response["Cache-Control"])
        return response.json()

    @override_settings(STOCKBILL_ENV="production")
    def test_production_reports_the_environment_only(self):
        self.assertEqual(self.get(), {"environment": "production"})

    @override_settings(STOCKBILL_ENV="development")
    def test_development_also_reports_the_database(self):
        db = settings.DATABASES["default"]
        body = self.get()
        self.assertEqual(body["environment"], "development")
        self.assertEqual(body["database"], f"{db['NAME']}@{db['HOST']}:{db['PORT']}")
        self.assertEqual(set(body), {"environment", "database"})

    @override_settings(STOCKBILL_ENV="staging")
    def test_staging_reports_the_database(self):
        self.assertEqual(self.get()["environment"], "staging")
        self.assertIn("database", self.get())

    @override_settings(STOCKBILL_ENV="development")
    def test_never_exposes_credentials(self):
        db = settings.DATABASES["default"]
        text = self.client.get("/api/meta/").content.decode()
        self.assertNotIn(db["PASSWORD"], text)
        self.assertNotIn(f'"{db["USER"]}', text)

    def test_needs_no_login(self):
        self.assertEqual(self.client.get("/api/meta/").status_code, 200)

    def test_only_get_and_head(self):
        self.assertEqual(self.client.post("/api/meta/").status_code, 405)


PROBE = "from divya_enterprises import settings as s; print(s.STOCKBILL_ENV)"


def load_settings(value):
    return subprocess.run(
        [sys.executable, "-c", PROBE], cwd=settings.BASE_DIR, env={**os.environ, "STOCKBILL_ENV": value},
        capture_output=True, text=True, timeout=60,
    )


class StockbillEnvSettingTests(SimpleTestCase):
    def test_defaults_to_production(self):
        result = load_settings("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "production")

    def test_accepts_known_values_case_insensitively(self):
        result = load_settings(" Development ")
        self.assertEqual(result.stdout.strip(), "development", result.stderr)

    def test_rejects_unknown_values(self):
        result = load_settings("prod")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STOCKBILL_ENV must be one of", result.stderr)


class MetaBusinessNameTests(TestCase):
    """Release B1: signed-in requests also get the shop name for the sidebar."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import User
        from billing.models import BusinessProfile

        cls.user = User.objects.create_user(username="meta-staff", password="Pass-12345!", role="staff")
        cls.token = Token.objects.create(user=cls.user)
        BusinessProfile.objects.create(business_name="Sharma General Store", gstin="27AAAAA0000A1Z5",
                                       registered_address="Pune", state="Maharashtra", state_code="27")

    @override_settings(STOCKBILL_ENV="production")
    def test_token_authenticated_request_gets_the_business_name(self):
        body = self.client.get("/api/meta/", HTTP_AUTHORIZATION=f"Token {self.token.key}").json()
        self.assertEqual(body, {"environment": "production", "business_name": "Sharma General Store"})

    @override_settings(STOCKBILL_ENV="production")
    def test_session_authenticated_request_gets_the_business_name(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/meta/").json()["business_name"], "Sharma General Store")

    @override_settings(STOCKBILL_ENV="production")
    def test_anonymous_request_gets_no_business_name(self):
        self.assertEqual(self.client.get("/api/meta/").json(), {"environment": "production"})

    @override_settings(STOCKBILL_ENV="development")
    def test_invalid_token_is_treated_as_anonymous(self):
        response = self.client.get("/api/meta/", HTTP_AUTHORIZATION="Token not-a-real-token")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("business_name", response.json())
        self.assertEqual(response.json()["environment"], "development")

    @override_settings(STOCKBILL_ENV="production")
    def test_profile_endpoint_stays_admin_only(self):
        response = self.client.get("/api/business-profile/", HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.assertEqual(response.status_code, 403)
