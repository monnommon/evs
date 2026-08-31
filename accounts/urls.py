from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="auth-register"),
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("password-reset/", views.PasswordResetView.as_view(), name="auth-password-reset"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", views.MeView.as_view(), name="auth-me"),
]