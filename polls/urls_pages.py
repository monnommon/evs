from django.urls import path

from . import views_pages

urlpatterns = [
    # Public results page (closed polls)
    path("polls/<uuid:poll_id>/results/", views_pages.poll_results, name="page-poll-results"),
    # Admin panel (session auth, server-side Role checks)
    path("panel/login/", views_pages.panel_login, name="panel-login"),
    path("panel/logout/", views_pages.panel_logout, name="panel-logout"),
    path("panel/", views_pages.panel_dashboard, name="panel-dashboard"),
    path("panel/polls/new/", views_pages.panel_poll_new, name="panel-poll-new"),
    path("panel/polls/new/create", views_pages.panel_poll_create, name="panel-poll-create"),
    path("panel/polls/<uuid:poll_id>/edit/", views_pages.panel_poll_edit, name="panel-poll-edit"),
    path("panel/polls/<uuid:poll_id>/update/", views_pages.panel_poll_update, name="panel-poll-update"),
    path("panel/polls/<uuid:poll_id>/finalize/", views_pages.panel_poll_finalize, name="panel-poll-finalize"),
    path("panel/polls/<uuid:poll_id>/generate-link/", views_pages.panel_generate_link, name="panel-generate-link"),
    path("panel/polls/<uuid:poll_id>/results/", views_pages.panel_poll_results, name="panel-poll-results"),
    path("panel/polls/<uuid:poll_id>/delete/", views_pages.panel_poll_delete, name="panel-poll-delete"),
    path("panel/users/", views_pages.panel_users, name="panel-users"),
    path("panel/users/<uuid:user_id>/role/", views_pages.panel_user_role, name="panel-user-role"),
]