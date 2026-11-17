from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import generics, permissions
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .permissions import IsAdminUser
from .serializers import StaffUserSerializer, UserSerializer

User = get_user_model()


class LoginView(ObtainAuthToken):
    """POST username/password -> {"token": ...}; same contract as DRF's view.

    Every successful login issues a brand-new token and deletes the user's
    old one, so the token lifetime (TOKEN_TTL_HOURS) restarts at login. DRF
    keeps one token per user, so logging in on a second device signs the
    first one out. Attempts are throttled per client ("login" scope).
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        with transaction.atomic():
            # Row lock serialises two simultaneous logins of the same user,
            # which would otherwise race on Token's one-per-user constraint.
            User.objects.select_for_update().only("pk").get(pk=user.pk)
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
        return Response({"token": token.key})


class UserListCreateView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    queryset = User.objects.all().order_by("id")


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    queryset = User.objects.all()


class StaffUserListView(generics.ListAPIView):
    serializer_class = StaffUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = User.objects.filter(is_active=True).order_by("id")


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)
