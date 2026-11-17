"""Django admin (mounted only with ENABLE_DJANGO_ADMIN): login sessions.

Each knox AuthToken is one signed-in device. Admins can see a user's
sessions (filter or search by user) and revoke them with the standard
"Delete selected" action or the delete button; the device is signed out on
its next request. Tokens are only ever created by logging in, never here.
"""

from django.contrib import admin
from django.utils import timezone
from knox.admin import AuthTokenAdmin as KnoxAuthTokenAdmin
from knox.models import AuthToken

admin.site.unregister(AuthToken)


@admin.register(AuthToken)
class LoginSessionAdmin(KnoxAuthTokenAdmin):
    list_display = ("user", "token_key", "created", "expiry", "is_active")
    list_filter = ("user",)
    ordering = ("-created",)
    readonly_fields = ("user", "token_key", "created", "expiry")
    fields = ("user", "token_key", "created", "expiry")

    @admin.display(boolean=True, description="Active")
    def is_active(self, obj):
        return obj.expiry is None or obj.expiry > timezone.now()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
