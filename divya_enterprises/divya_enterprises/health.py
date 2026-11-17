"""Unauthenticated liveness check for uptime monitoring (GET /api/health/).

A plain Django view, outside DRF, so no authentication, throttling or
content negotiation applies. It runs ``SELECT 1`` and reports only whether
that worked: no version, settings or data.
"""

import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # any database failure means "not healthy"
        logger.warning("Health check: database query failed", exc_info=True)
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
