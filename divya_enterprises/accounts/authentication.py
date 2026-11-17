"""Token authentication with a fixed lifetime.

The frontend keeps sending ``Authorization: Token <key>``. A token older than
``settings.TOKEN_TTL_HOURS`` (measured from ``Token.created``, i.e. the login
that issued it) is deleted and the request is rejected with 401, which sends
the user back to the login page.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

SESSION_EXPIRED_MESSAGE = "Your session has expired. Please log in again."


def token_expired(token, now=None):
    now = now or timezone.now()
    return token.created <= now - timedelta(hours=settings.TOKEN_TTL_HOURS)


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token_expired(token):
            token.delete()
            raise AuthenticationFailed(SESSION_EXPIRED_MESSAGE)
        return user, token
