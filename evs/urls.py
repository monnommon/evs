from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path
from django.views.decorators.http import require_GET


@require_GET
def root_redirect(request):
    """GET / — send browsers to the panel; anonymous users hit the login gate there."""
    return redirect("panel-dashboard")


urlpatterns = [
    path("", root_redirect, name="root"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/admin/", include("polls.urls_admin")),
    path("", include("polls.urls_public")),
    path("", include("polls.urls_pages")),
]