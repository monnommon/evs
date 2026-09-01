from django.contrib import admin
from django.shortcuts import redirect, render
from django.urls import include, path
from django.views.decorators.http import require_GET


@require_GET
def root_redirect(request):
    """GET / — landing for voters; admins click through to the panel."""
    if "text/html" not in request.headers.get("Accept", ""):
        return redirect("panel-dashboard")
    return render(request, "polls/landing.html")


urlpatterns = [
    path("", root_redirect, name="root"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/admin/", include("polls.urls_admin")),
    path("", include("polls.urls_public")),
    path("", include("polls.urls_pages")),
]