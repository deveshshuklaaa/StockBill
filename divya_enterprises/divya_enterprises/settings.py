import os
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Comma-separated env value as a list; an explicitly empty value gives []."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_int(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a whole number, got {value!r}.") from exc


# Fail closed: production is the default. Local development and the shop
# PC's StockBill.bat must set DEBUG=True in .env explicitly.
DEBUG = env_bool("DEBUG", False)

DEV_SECRET_KEY = "django-insecure-dev-key"
# Values that must never be used outside DEBUG: the dev fallback and the
# placeholder shipped in .env.production.example.
INSECURE_SECRET_KEYS = {DEV_SECRET_KEY, "change-me-to-a-long-random-string"}
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not DEBUG and (not SECRET_KEY or SECRET_KEY in INSECURE_SECRET_KEYS):
    raise ImproperlyConfigured(
        "SECRET_KEY is missing or is a development placeholder while DEBUG is off. "
        "Set a long random SECRET_KEY in .env (or DEBUG=True for local development)."
    )
SECRET_KEY = SECRET_KEY or DEV_SECRET_KEY

# Which installation this is. Anything other than "production" shows a red
# banner on every screen (frontend, via GET /api/meta/) so a development or
# staging copy can never be mistaken for the shop. Default is production, so
# an installation that does not set it shows nothing.
STOCKBILL_ENVIRONMENTS = ("production", "development", "staging")
STOCKBILL_ENV = (os.getenv("STOCKBILL_ENV") or "production").strip().lower()
if STOCKBILL_ENV not in STOCKBILL_ENVIRONMENTS:
    raise ImproperlyConfigured(
        f"STOCKBILL_ENV must be one of {', '.join(STOCKBILL_ENVIRONMENTS)}; got {STOCKBILL_ENV!r}."
    )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
# Dev only: the Vite dev server (5173) calls the API on 8000. In production
# nginx serves the frontend and /api from one origin, so set this to empty.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
# Idempotency-Key is sent by purchase/invoice POSTs; without it in the
# preflight allow-list the browser blocks the request as a CORS error and
# the frontend misreports it as "server could not be reached".
CORS_ALLOW_HEADERS = list(default_headers) + [
    "idempotency-key",
]
# Let the browser read the server's filename on CSV/XLSX downloads.
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "knox",
    "accounts",
    "customers",
    "inventory",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "divya_enterprises.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "divya_enterprises.wsgi.application"
ASGI_APPLICATION = "divya_enterprises.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "divya_enterprises"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# GST document-number prefixes (CGST Rules 46(b) / 53). The full number is
# "<prefix>/<fy>/<serial>" and must stay within 16 characters; billing.numbering
# refuses to issue a number that would not.
INVOICE_NUMBER_PREFIX = os.getenv("INVOICE_NUMBER_PREFIX", "DE")
CREDIT_NOTE_NUMBER_PREFIX = os.getenv("CREDIT_NOTE_NUMBER_PREFIX", "CN")

STATIC_URL = "/static/"
# collectstatic target (Django admin assets in the production image).
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

# Django admin is mounted only when explicitly enabled; by default it follows
# DEBUG, so it is off in production unless ENABLE_DJANGO_ADMIN=true.
ENABLE_DJANGO_ADMIN = env_bool("ENABLE_DJANGO_ADMIN", DEBUG)

# API tokens (django-rest-knox) expire this many hours after login. Each
# login gets its own token, so several devices can be signed in at once and
# logging out revokes only that device's token.
TOKEN_TTL_HOURS = env_int("TOKEN_TTL_HOURS", 168)
if TOKEN_TTL_HOURS < 1:
    raise ImproperlyConfigured("TOKEN_TTL_HOURS must be at least 1.")
REST_KNOX = {
    "TOKEN_TTL": timedelta(hours=TOKEN_TTL_HOURS),
    "AUTO_REFRESH": False,
    # Keeps the frontend header unchanged: "Authorization: Token <key>".
    "AUTH_HEADER_PREFIX": "Token",
}

# Shared across Gunicorn workers (login throttling). Create the table with
# "python manage.py createcachetable"; accounts/0002 also creates it on migrate.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "stockbill_cache",
    }
}

# Security headers. TLS ends at Cloudflare, so SECURE_SSL_REDIRECT stays off
# (the app only ever sees plain HTTP from nginx; a redirect would loop).
SECURE_SSL_REDIRECT = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    # nginx passes the original scheme on; trust it only from that proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start short; raise once the domain has run on HTTPS without trouble.
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = False

# Django prints request errors (500 tracebacks) to the console only when
# DEBUG is on; send warnings and errors to stderr so "docker compose logs"
# shows them in production too.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "stderr": {"class": "logging.StreamHandler", "level": os.getenv("LOG_LEVEL", "WARNING").upper()},
    },
    "root": {"handlers": ["stderr"], "level": "WARNING"},
    # 4xx responses are already in the access log; log only 5xx tracebacks.
    "loggers": {"django.request": {"level": "ERROR"}},
}

REST_FRAMEWORK = {
    # Token first: an unauthenticated or expired-token request gets 401 with
    # "WWW-Authenticate: Token" (DRF takes the header from the first class).
    # A logged-in user without the needed role still gets 403.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "knox.auth.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": os.getenv("LOGIN_THROTTLE_RATE", "5/min"),
    },
    # Number of proxies in front of Django that set X-Forwarded-For (nginx in
    # production), so throttling sees the real client address. Unset in dev.
    "NUM_PROXIES": env_int("NUM_PROXIES", None),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}
