from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/admin/", include("polls.urls_admin")),
    path("", include("polls.urls_public")),
    path("", include("polls.urls_pages")),
]