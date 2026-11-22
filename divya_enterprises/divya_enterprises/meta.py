"""GET /api/meta/: which installation this is, for the frontend.

Unauthenticated (the login page shows the environment banner too) and a
plain Django view, so it never answers 401/403. Production reports only
{"environment": "production"}. Other environments also report the
database as NAME@HOST:PORT (never the user or password), so it is obvious
which data a screen is showing.

Signed-in requests (any of the API's authentication methods, e.g. the
frontend's "Authorization: Token ...") also get the shop's
"business_name" from the Business Profile, for the sidebar. A missing,
invalid or expired credential is treated as anonymous rather than an error.
"""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.settings import api_settings


def _authenticated_user(request):
    drf_request = Request(request, authenticators=[auth() for auth in api_settings.DEFAULT_AUTHENTICATION_CLASSES])
    try:
        user = drf_request.user
    except APIException:
        return None
    return user if user is not None and user.is_authenticated else None


@never_cache
@require_safe
def meta(request):
    environment = settings.STOCKBILL_ENV
    body = {"environment": environment}
    if environment != "production":
        db = settings.DATABASES["default"]
        body["database"] = f"{db.get('NAME', '')}@{db.get('HOST') or 'localhost'}:{db.get('PORT') or '5432'}"
    if _authenticated_user(request) is not None:
        from billing.models import BusinessProfile

        profile = BusinessProfile.objects.only("business_name").first()
        body["business_name"] = profile.business_name if profile else ""
    return JsonResponse(body)
