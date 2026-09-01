from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from rest_framework import generics, permissions, status, views
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from audit.utils import log_event
from .models import User
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        log_event("user_registered", "User", str(user.id), {"email": user.email}, created_by=user)
        return Response(
            {"user": UserSerializer(user).data, "refresh": str(refresh), "access": str(refresh.access_token)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, email=serializer.validated_data["email"].lower().strip(), password=serializer.validated_data["password"])
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        from django.utils import timezone

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token), "user": UserSerializer(user).data})


class LogoutView(views.APIView):
    """Blacklist the provided refresh token (JWT invalidation)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "refresh token required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh_token).blacklist()
        except Exception:
            return Response({"detail": "invalid token"}, status=status.HTTP_400_BAD_REQUEST)
        log_event("user_logout", "User", str(request.user.id), {}, created_by=request.user)
        return Response({"detail": "logged out"})


class PasswordResetView(views.APIView):
    """Issue a signed one-time reset token (email delivery via console in dev)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            user = None
        if user is not None:
            from django.contrib.auth.tokens import default_token_generator
            from django.utils.encoding import force_bytes
            from django.utils.http import urlsafe_base64_encode

            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/api/auth/password-reset/confirm/?uid={uidb64}&token={token}"
            send_mail(
                subject="EVS password reset",
                message=f"Reset your password using this link:\n{reset_url}\nIf you did not request this, ignore this email.",
                from_email=None,
                recipient_list=[email],
                fail_silently=True,
            )
            log_event("password_reset_requested", "User", str(user.id), {"email": user.email})
        return Response({"detail": "If the email exists, a reset link has been sent."})


class PasswordResetConfirmView(views.APIView):
    """Validate a reset token and replace the user's password."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode

        uid = request.data.get("uid") or request.query_params.get("uid")
        token = request.data.get("token") or request.query_params.get("token")
        new_password = request.data.get("new_password") or ""
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
        if user is None or not token or not default_token_generator.check_token(user, token):
            return Response({"detail": "Invalid or expired reset link."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        log_event("password_reset_completed", "User", str(user.id), {}, created_by=user)
        return Response({"detail": "Password has been reset."})


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
