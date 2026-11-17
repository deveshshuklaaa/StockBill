from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from knox.models import AuthToken
from knox.settings import knox_settings
from knox.views import LogoutAllView as KnoxLogoutAllView
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions
from rest_framework.fields import DateTimeField
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsAdminUser
from .serializers import LoginSerializer, StaffUserSerializer, UserSerializer
from .throttling import LoginRateThrottle

User = get_user_model()


class LoginView(APIView):
    """POST username/password -> {"token": ..., "expiry": ...}.

    Issues a new knox token for this device; the user's other tokens (other
    devices) stay valid. The token expires TOKEN_TTL_HOURS after login.
    Attempts are throttled per client address ("login" scope; behind
    Cloudflare the address comes from CF-Connecting-IP, see throttling.py).
    """

    # Anonymous by design: a stale token left in the browser must not turn a
    # login attempt into a 401.
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        instance, token = AuthToken.objects.create(user=user, expiry=knox_settings.TOKEN_TTL)
        user_logged_in.send(sender=user.__class__, request=request, user=user)
        return Response({"token": token, "expiry": DateTimeField().to_representation(instance.expiry)})


class LogoutView(KnoxLogoutView):
    """POST: revoke the token that made this request (this device only). 204."""


class LogoutAllView(KnoxLogoutAllView):
    """POST: revoke every token of this user (all devices). 204. API only."""


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
