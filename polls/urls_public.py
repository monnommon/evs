from django.urls import path

from . import views_public

urlpatterns = [
    # Public anonymous voting (link-based)
    path("poll/<str:token>/", views_public.PollByTokenView.as_view(), name="poll-by-token"),
    path("poll/<str:token>/vote/", views_public.AnonymousVoteView.as_view(), name="poll-anon-vote"),
    path("poll/<str:token>/confirm/", views_public.AnonymousConfirmView.as_view(), name="poll-anon-confirm"),
    # Authenticated user voting
    path("polls/active/", views_public.ActivePollsView.as_view(), name="polls-active"),
    path("polls/<uuid:pk>/", views_public.PollDetailView.as_view(), name="poll-detail"),
    path("polls/<uuid:pk>/vote/", views_public.AuthenticatedVoteView.as_view(), name="poll-vote"),
    path("my-votes/", views_public.MyVotesView.as_view(), name="my-votes"),
]