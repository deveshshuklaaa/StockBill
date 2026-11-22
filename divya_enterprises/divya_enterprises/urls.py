from django.contrib import admin
from django.urls import include, path

from .meta import meta

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/meta/", meta, name="meta"),
    path("api/", include("accounts.urls")),
    path("api/", include("customers.urls")),
    path("api/", include("inventory.urls")),
    path("api/", include("billing.urls")),
]
