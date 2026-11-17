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
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from accounts.authentication import SESSION_EXPIRED_MESSAGE
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


class TokenExpiryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(username="clerk", password="Counter-pass-42", role=User.ROLE_STAFF)

    def authed(self, key):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return self.client.get("/api/auth/me/")

    def test_fresh_token_works(self):
        token = Token.objects.create(user=self.user)
        response = self.authed(token.key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "clerk")

    def test_expired_token_gets_401_and_is_deleted(self):
        token = Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(
            created=timezone.now() - timedelta(hours=settings.TOKEN_TTL_HOURS, minutes=1)
        )
        response = self.authed(token.key)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], SESSION_EXPIRED_MESSAGE)
        self.assertEqual(response["WWW-Authenticate"], "Token")
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
        # Still rejected afterwards (now as an unknown token).
        self.assertEqual(self.authed(token.key).status_code, 401)

    def test_token_just_inside_lifetime_still_works(self):
        token = Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(
            created=timezone.now() - timedelta(hours=settings.TOKEN_TTL_HOURS) + timedelta(minutes=5)
        )
        self.assertEqual(self.authed(token.key).status_code, 200)

    @override_settings(TOKEN_TTL_HOURS=1)
    def test_lifetime_comes_from_settings(self):
        token = Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(minutes=61))
        self.assertEqual(self.authed(token.key).status_code, 401)

    def test_login_rotates_the_token(self):
        old = Token.objects.create(user=self.user)
        response = self.client.post("/api/auth/token/", {"username": "clerk", "password": "Counter-pass-42"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"token"})
        new_key = response.data["token"]
        self.assertNotEqual(new_key, old.key)
        self.assertEqual(list(Token.objects.filter(user=self.user).values_list("key", flat=True)), [new_key])
        self.assertEqual(self.authed(old.key).status_code, 401)
        self.assertEqual(self.authed(new_key).status_code, 200)

    def test_login_after_expiry_issues_a_working_token(self):
        old = Token.objects.create(user=self.user)
        Token.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(days=30))
        self.assertEqual(self.authed(old.key).status_code, 401)
        self.client.credentials()
        response = self.client.post("/api/auth/token/", {"username": "clerk", "password": "Counter-pass-42"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.authed(response.data["token"]).status_code, 200)

    def test_wrong_password_is_400_and_keeps_existing_token(self):
        token = Token.objects.create(user=self.user)
        response = self.client.post("/api/auth/token/", {"username": "clerk", "password": "wrong"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Token.objects.filter(pk=token.pk).exists())

    def test_anonymous_gets_401_but_wrong_role_gets_403(self):
        self.assertEqual(self.client.get("/api/users/").status_code, 401)
        token = Token.objects.create(user=self.user)  # staff, not admin
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/users/").status_code, 403)


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
