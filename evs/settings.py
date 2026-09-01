import os
from datetime import timedelta
from pathlib import Path

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-key-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "accounts",
    "polls",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "evs.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "evs.wsgi.application"


def parse_database_url(url):
    """Minimal DATABASE_URL parser (postgres://user:pass@host:port/dbname)."""
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    options = {"CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60"))}
    if parsed.scheme.startswith("postgres"):
        options.update(
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": unquote(parsed.path.lstrip("/")) or "evs",
                "USER": unquote(parsed.username or "evs"),
                "PASSWORD": unquote(parsed.password or ""),
                "HOST": parsed.hostname or "db",
                "PORT": parsed.port or 5432,
            }
        )
    elif parsed.scheme == "sqlite":
        # sqlite:///relative.db is relative; sqlite:////absolute/path.db keeps
        # its leading slash. Stripping every slash silently redirected an
        # explicitly absolute database into the project directory.
        sqlite_path = unquote(parsed.path)
        name = sqlite_path[1:] if sqlite_path.startswith("//") else sqlite_path.lstrip("/")
        options.update({"ENGINE": "django.db.backends.sqlite3", "NAME": name})
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")
    return options


_db_url = os.environ.get("DATABASE_URL")
DATABASES = {
    "default": parse_database_url(_db_url) if _db_url else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# i18n: Russian + English. English stays the default language so existing
# API/UI behavior is unchanged; RU is one click away via the switcher.
LANGUAGE_CODE = "en"

LANGUAGES = [
    ("ru", _("Russian")),
    ("en", _("English")),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "evs-noreply@example.com")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost")
