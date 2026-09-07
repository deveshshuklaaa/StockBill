from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    message = "Only admin users can access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "admin")


class IsStaffUser(BasePermission):
    message = "Only staff users can access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in {"admin", "staff"})
