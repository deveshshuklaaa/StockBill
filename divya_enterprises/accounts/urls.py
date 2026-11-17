from django.urls import path

from .views import (
    CurrentUserView,
    LoginView,
    LogoutAllView,
    LogoutView,
    StaffUserListView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path("auth/token/", LoginView.as_view(), name="auth-token"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/logoutall/", LogoutAllView.as_view(), name="auth-logout-all"),
    path("auth/me/", CurrentUserView.as_view(), name="auth-me"),
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("staff-users/", StaffUserListView.as_view(), name="staff-user-list"),
]
