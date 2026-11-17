"""Production hardening: fail-closed settings, token expiry, login throttling,
health endpoint and the Django-admin switch."""

import importlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import clear_url_caches
from django.utils import timezone
from knox.models import AuthToken
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import User

BACKEND_DIR = settings.BASE_DIR

SETTINGS_PROBE = """
import json
from divya_enterprises import settings as s
print(json.dumps({
    "DEBUG": s.DEBUG,
    "SECURE_PROXY_SSL_HEADER": getattr(s, "SECURE_PROXY_SSL_HEADER", None),
    "SESSION_COOKIE_SECURE": getattr(s, "SESSION_COOKIE_SECURE", False),
    "CSRF_COOKIE_SECURE": getattr(s, "CSRF_COOKIE_SECURE", False),
    "SECURE_SSL_REDIRECT": s.SECURE_SSL_REDIRECT,
    "SECURE_HSTS_SECONDS": getattr(s, "SECURE_HSTS_SECONDS", 0),
    "SECURE_CONTENT_TYPE_NOSNIFF": s.SECURE_CONTENT_TYPE_NOSNIFF,
    "X_FRAME_OPTIONS": s.X_FRAME_OPTIONS,
    "TIME_ZONE": s.TIME_ZONE,
    "ALLOWED_HOSTS": s.ALLOWED_HOSTS,
    "CSRF_TRUSTED_ORIGINS": s.CSRF_TRUSTED_ORIGINS,
    "CORS_ALLOWED_ORIGINS": s.CORS_ALLOWED_ORIGINS,
    "ENABLE_DJANGO_ADMIN": s.ENABLE_DJANGO_ADMIN,
}))
"""


def load_settings(**env):
    """Import the settings module in a fresh interpreter with the given env.

    Values set here (even empty ones) win over the repository .env, because
    python-dotenv never overrides variables that already exist.
    """
    child_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", SETTINGS_PROBE],
        cwd=BACKEND_DIR,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class FailClosedSettingsTests(SimpleTestCase):
    REAL_KEY = "a-real-production-key-" + "x" * 40

    def assert_refuses(self, **env):
        result = load_settings(**env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_debug_off_without_secret_key_refuses_to_start(self):
        self.assert_refuses(DEBUG="False", SECRET_KEY="")

    def test_debug_off_with_dev_default_key_refuses_to_start(self):
        self.assert_refuses(DEBUG="False", SECRET_KEY="django-insecure-dev-key")

    def test_debug_off_with_example_placeholder_refuses_to_start(self):
        self.assert_refuses(DEBUG="False", SECRET_KEY="change-me-to-a-long-random-string")

    def test_debug_defaults_to_off(self):
        # DEBUG unset/empty is production: a missing key must still refuse.
        self.assert_refuses(DEBUG="", SECRET_KEY="")

    def test_debug_on_without_key_still_starts_for_local_dev(self):
        result = load_settings(DEBUG="True", SECRET_KEY="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["DEBUG"])

    def test_production_security_settings(self):
        result = load_settings(
            DEBUG="False",
            SECRET_KEY=self.REAL_KEY,
            ALLOWED_HOSTS="stockbill.example.com, localhost",
            CSRF_TRUSTED_ORIGINS="https://stockbill.example.com",
            CORS_ALLOWED_ORIGINS="",
            ENABLE_DJANGO_ADMIN="",
            SECURE_HSTS_SECONDS="600",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertFalse(values["DEBUG"])
        self.assertEqual(values["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertTrue(values["SESSION_COOKIE_SECURE"])
        self.assertTrue(values["CSRF_COOKIE_SECURE"])
        self.assertFalse(values["SECURE_SSL_REDIRECT"])  # TLS ends at Cloudflare
        self.assertEqual(values["SECURE_HSTS_SECONDS"], 600)
        self.assertTrue(values["SECURE_CONTENT_TYPE_NOSNIFF"])
        self.assertEqual(values["X_FRAME_OPTIONS"], "DENY")
        self.assertEqual(values["TIME_ZONE"], "Asia/Kolkata")
        self.assertEqual(values["ALLOWED_HOSTS"], ["stockbill.example.com", "localhost"])
        self.assertEqual(values["CSRF_TRUSTED_ORIGINS"], ["https://stockbill.example.com"])
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], [])
        self.assertFalse(values["ENABLE_DJANGO_ADMIN"])  # follows DEBUG when unset


class TokenSessionTests(TestCase):
    """knox tokens: one per login (device), fixed lifetime, per-device logout."""

    PASSWORD = "Counter-pass-42"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="clerk", password=self.PASSWORD, role=User.ROLE_STAFF)

    def login(self, client=None):
        client = client or APIClient()
        response = client.post("/api/auth/token/", {"username": "clerk", "password": self.PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def me(self, key):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return client.get("/api/auth/me/")

    def post_as(self, key, url):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return client.post(url)

    def test_login_response_shape_and_lifetime(self):
        before = timezone.now()
        data = self.login().data
        self.assertEqual(set(data), {"token", "expiry"})
        token = AuthToken.objects.get(user=self.user)
        expected = before + timedelta(hours=settings.TOKEN_TTL_HOURS)
        self.assertAlmostEqual(token.expiry.timestamp(), expected.timestamp(), delta=60)
        self.assertEqual(self.me(data["token"]).status_code, 200)
        self.assertEqual(self.me(data["token"]).data["username"], "clerk")

    def test_two_devices_stay_signed_in_together(self):
        shop_pc = self.login().data["token"]
        phone = self.login().data["token"]
        self.assertNotEqual(shop_pc, phone)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 2)
        self.assertEqual(self.me(shop_pc).status_code, 200)
        self.assertEqual(self.me(phone).status_code, 200)

    def test_logout_revokes_only_this_device(self):
        shop_pc = self.login().data["token"]
        phone = self.login().data["token"]
        self.assertEqual(self.post_as(phone, "/api/auth/logout/").status_code, 204)
        self.assertEqual(self.me(phone).status_code, 401)
        self.assertEqual(self.me(shop_pc).status_code, 200)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 1)

    def test_logout_all_revokes_every_device(self):
        shop_pc = self.login().data["token"]
        phone = self.login().data["token"]
        self.assertEqual(self.post_as(shop_pc, "/api/auth/logoutall/").status_code, 204)
        self.assertEqual(self.me(shop_pc).status_code, 401)
        self.assertEqual(self.me(phone).status_code, 401)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_logout_needs_a_valid_token(self):
        self.assertEqual(APIClient().post("/api/auth/logout/").status_code, 401)
        self.assertEqual(self.post_as("not-a-real-token", "/api/auth/logoutall/").status_code, 401)

    def test_expired_token_gets_401_and_is_deleted(self):
        key = self.login().data["token"]
        AuthToken.objects.filter(user=self.user).update(expiry=timezone.now() - timedelta(minutes=1))
        response = self.me(key)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Token")
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_no_auto_refresh(self):
        key = self.login().data["token"]
        expiry = AuthToken.objects.get(user=self.user).expiry
        self.me(key)
        self.assertEqual(AuthToken.objects.get(user=self.user).expiry, expiry)

    def test_tokens_are_not_stored_in_plain_text(self):
        key = self.login().data["token"]
        stored = AuthToken.objects.get(user=self.user)
        self.assertNotEqual(stored.digest, key)
        self.assertTrue(key.startswith(stored.token_key))

    def test_old_drf_tokens_no_longer_work(self):
        # A 40-hex DRF authtoken key still in a browser after the deploy.
        self.assertEqual(self.me("9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b").status_code, 401)

    def test_login_ignores_a_stale_token_header(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token expired-or-revoked-token")
        self.assertIn("token", self.login(client).data)

    def test_wrong_password_is_400_with_drf_style_error(self):
        response = APIClient().post("/api/auth/token/", {"username": "clerk", "password": "wrong"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["non_field_errors"], ["Unable to log in with provided credentials."])
        self.assertFalse(AuthToken.objects.exists())

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = APIClient().post("/api/auth/token/", {"username": "clerk", "password": self.PASSWORD}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_anonymous_gets_401_but_wrong_role_gets_403(self):
        self.assertEqual(APIClient().get("/api/users/").status_code, 401)
        key = self.login().data["token"]  # staff, not admin
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        self.assertEqual(client.get("/api/users/").status_code, 403)


class LoginSessionAdminTests(TestCase):
    """Django admin lists login sessions and lets an admin revoke them."""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(username="boss", password="Boss-pass-42", email="")
        self.clerk = User.objects.create_user(username="clerk", password="Counter-pass-42")
        self.clerk_tokens = [AuthToken.objects.create(user=self.clerk)[0] for _ in range(2)]
        AuthToken.objects.create(user=self.admin_user)
        self.client.force_login(self.admin_user)

    def admin_get(self, url):
        with override_settings(ENABLE_DJANGO_ADMIN=True):
            import divya_enterprises.urls as root_urls

            importlib.reload(root_urls)
            clear_url_caches()
            try:
                return self.client.get(url)
            finally:
                importlib.reload(root_urls)
                clear_url_caches()

    def admin_post(self, url, data):
        with override_settings(ENABLE_DJANGO_ADMIN=True):
            import divya_enterprises.urls as root_urls

            importlib.reload(root_urls)
            clear_url_caches()
            try:
                return self.client.post(url, data)
            finally:
                importlib.reload(root_urls)
                clear_url_caches()

    def test_lists_one_users_sessions(self):
        response = self.admin_get(f"/admin/knox/authtoken/?user__id__exact={self.clerk.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 2)

    def test_admin_can_revoke_a_session(self):
        target = self.clerk_tokens[0]
        response = self.admin_post(
            "/admin/knox/authtoken/",
            {"action": "delete_selected", "_selected_action": [target.pk], "post": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuthToken.objects.filter(pk=target.pk).exists())
        self.assertEqual(AuthToken.objects.filter(user=self.clerk).count(), 1)

    def test_sessions_cannot_be_created_or_edited_in_admin(self):
        self.assertEqual(self.admin_get("/admin/knox/authtoken/add/").status_code, 403)


@patch.object(ScopedRateThrottle, "THROTTLE_RATES", {"login": "3/min"})
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        User.objects.create_user(username="clerk", password="Counter-pass-42")

    def attempt(self, password="wrong", ip="203.0.113.7"):
        return self.client.post(
            "/api/auth/token/", {"username": "clerk", "password": password}, format="json", REMOTE_ADDR=ip
        )

    def test_request_after_the_limit_gets_429(self):
        for _ in range(3):
            self.assertEqual(self.attempt().status_code, 400)
        response = self.attempt(password="Counter-pass-42")  # even the right password
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_limit_is_per_client_address(self):
        for _ in range(3):
            self.attempt(ip="203.0.113.7")
        self.assertEqual(self.attempt(ip="203.0.113.7").status_code, 429)
        self.assertEqual(self.attempt(password="Counter-pass-42", ip="198.51.100.9").status_code, 200)

    def test_throttle_uses_the_shared_database_cache(self):
        self.assertEqual(settings.CACHES["default"]["BACKEND"], "django.core.cache.backends.db.DatabaseCache")
        self.attempt()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {settings.CACHES['default']['LOCATION']}")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_default_rate_comes_from_settings(self):
        from rest_framework.settings import api_settings

        self.assertIn("login", api_settings.DEFAULT_THROTTLE_RATES)


class HealthEndpointTests(TestCase):
    def test_ok_without_authentication(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_503_when_database_query_fails(self):
        with patch("divya_enterprises.health.connection.cursor", side_effect=OperationalError("db down")):
            with self.assertLogs("divya_enterprises.health", level="WARNING"):
                response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_only_get_and_head(self):
        self.assertEqual(self.client.head("/api/health/").status_code, 200)
        self.assertEqual(self.client.post("/api/health/").status_code, 405)


class DjangoAdminSwitchTests(SimpleTestCase):
    def reload_urls(self):
        import divya_enterprises.urls as root_urls

        importlib.reload(root_urls)
        clear_url_caches()

    def tearDown(self):
        self.reload_urls()  # back to the real setting

    @override_settings(ENABLE_DJANGO_ADMIN=False)
    def test_admin_is_404_when_disabled(self):
        self.reload_urls()
        self.assertEqual(self.client.get("/admin/").status_code, 404)
        self.assertEqual(self.client.get("/admin/login/").status_code, 404)

    @override_settings(ENABLE_DJANGO_ADMIN=True)
    def test_admin_is_mounted_when_enabled(self):
        self.reload_urls()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
