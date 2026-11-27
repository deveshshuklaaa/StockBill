"""GET /api/meta/: which installation this is, for the frontend's banner.

Unauthenticated (the login page shows the banner too) and a plain Django
view, so no DRF authentication or throttling applies. Production reports
only {"environment": "production"}. Other environments also report the
database as NAME@HOST:PORT (never the user or password), so it is obvious
which data a screen is showing.
"""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def meta(request):
    environment = settings.STOCKBILL_ENV
    body = {"environment": environment}
    if environment != "production":
        db = settings.DATABASES["default"]
        body["database"] = f"{db.get('NAME', '')}@{db.get('HOST') or 'localhost'}:{db.get('PORT') or '5432'}"
    return JsonResponse(body)
