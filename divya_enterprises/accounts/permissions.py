from rest_framework.permissions import BasePermission

from .models import User


class IsAdminUser(BasePermission):
    message = "Only admin users can access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.normalized_role == User.ROLE_ADMIN)


class IsStaffUser(BasePermission):
    message = "Only staff users can access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.normalized_role in {User.ROLE_ADMIN, User.ROLE_STAFF})


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and request.user.normalized_role == User.ROLE_ADMIN)
