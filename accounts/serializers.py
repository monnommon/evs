from rest_framework import serializers

from .models import Role, User


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def save(self):
        from .models import Role

        Role.ensure_defaults()
        email = self.validated_data["email"]
        user = User.objects.create_user(email=email, password=self.validated_data["password"], role=Role.objects.get(name=Role.Roles.USER))
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = ["id", "email", "role", "role_name", "is_active", "created_at", "last_login"]
        read_only_fields = ["id", "email", "created_at", "last_login"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "permissions"]


class ChangeUserRoleSerializer(serializers.Serializer):
    role_id = serializers.UUIDField()