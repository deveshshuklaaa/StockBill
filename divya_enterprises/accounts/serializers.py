from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    normalized_role = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "normalized_role",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]


class StaffUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    """Username/password check with the same fields and error responses as
    DRF's AuthTokenSerializer, which the login form was built against."""

    username = serializers.CharField(write_only=True)
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False, write_only=True)

    def validate(self, attrs):
        user = authenticate(request=self.context.get("request"), username=attrs["username"], password=attrs["password"])
        if not user:
            raise serializers.ValidationError("Unable to log in with provided credentials.", code="authorization")
        attrs["user"] = user
        return attrs
