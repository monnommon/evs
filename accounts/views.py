import secrets

from django.contrib.auth import authenticate
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
            reset_url = f"{request.build_absolute_uri('/').rstrip('/')}/api/auth/password-reset/confirm/?uid={uidb64}&token={token}"
            send_mail(
                subject="EVS password reset",
                message=f"Reset your password using this link:\n{reset_url}\nIf you did not request this, ignore this email.",
                from_email=None,
                recipient_list=[email],
                fail_silently=True,
            )
            log_event("password_reset_requested", "User", str(user.id), {"email": user.email})
        return Response({"detail": "If the email exists, a reset link has been sent."})


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user