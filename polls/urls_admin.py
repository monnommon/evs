from django.urls import path

from . import views_admin, views_public

urlpatterns = [
    # Admin panel API
    path("polls/", views_admin.AdminPollListView.as_view(), name="admin-poll-list"),
    path("polls/<uuid:pk>/", views_admin.AdminPollDetailView.as_view(), name="admin-poll-detail"),
    path("polls/<uuid:pk>/results/", views_admin.AdminPollResultsView.as_view(), name="admin-poll-results"),
    path("polls/<uuid:pk>/finalize/", views_admin.AdminFinalizePollView.as_view(), name="admin-poll-finalize"),
    path("polls/<uuid:pk>/generate-link/", views_admin.AdminGenerateLinkView.as_view(), name="admin-generate-link"),
    path("users/", views_admin.AdminUserListView.as_view(), name="admin-user-list"),
    path("users/<uuid:pk>/role/", views_admin.AdminChangeUserRoleView.as_view(), name="admin-user-role"),
    path("roles/", views_admin.AdminRoleListView.as_view(), name="admin-role-list"),
    path("audit/verify/", views_admin.AdminAuditVerifyView.as_view(), name="admin-audit-verify"),
]