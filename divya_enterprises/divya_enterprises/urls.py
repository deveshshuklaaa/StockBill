from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from .health import health
from .meta import meta

urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/meta/", meta, name="meta"),
    path("api/", include("accounts.urls")),
    path("api/", include("customers.urls")),
    path("api/", include("inventory.urls")),
    path("api/", include("billing.urls")),
]

# Mounted only when ENABLE_DJANGO_ADMIN is on (off by default in production).
if settings.ENABLE_DJANGO_ADMIN:
    urlpatterns.insert(0, path("admin/", admin.site.urls))
