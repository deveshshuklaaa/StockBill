from django.urls import path

from .views import CurrentUserView, UserDetailView, UserListCreateView, StaffUserListView, obtain_auth_token

urlpatterns = [
    path("auth/token/", obtain_auth_token, name="auth-token"),
    path("auth/me/", CurrentUserView.as_view(), name="auth-me"),
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("staff-users/", StaffUserListView.as_view(), name="staff-user-list"),
]
