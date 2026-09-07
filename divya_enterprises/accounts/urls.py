from django.urls import path

from .views import UserDetailView, UserListCreateView, StaffUserListView

urlpatterns = [
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("staff-users/", StaffUserListView.as_view(), name="staff-user-list"),
]
