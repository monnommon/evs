import hashlib
import hmac

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from rest_framework import generics, permissions, status, views
from rest_framework.response import Response

from audit.utils import log_event
from .models import AnonymousSession, Option, Poll, PollStatus, Vote
from .serializers import PollSerializer, VoteResultSerializer, VoteSerializer
from .views_admin import AdminOrResultsViewer


def _cast_vote(poll, user, option_ids, fingerprint_hash=None, anonymous_session=None):
    """Shared vote creation with audit logging. Caller has validated inputs."""
    vote = Vote.objects.create(
        poll=poll,
        user=user,
        fingerprint_hash=fingerprint_hash,
        anonymous_session=anonymous_session,
    )
    vote.options.set(option_ids)
    event = "anonymous_vote_cast" if user is None else "vote_cast"
    log_event(
        event,
        "Poll",
        str(poll.id),
        {"vote_id": str(vote.id), "option_ids": [str(o) for o in option_ids]},
        created_by=user,
    )
    return vote


def _wants_html(request):
    return "text/html" in request.headers.get("Accept", "")


def _is_form_post(request):
    ct = request.content_type or ""
    return request.method == "POST" and ("form" in ct or "multipart" in ct)


def _anon_vote_error(session, poll, now):
    """Shared refusal checks for anonymous voting (JSON API and HTML form)."""
    if session.is_expired or poll.end_at < now:
        return ("This voting link has expired.", status.HTTP_410_GONE)
    if poll.is_finalized:
        return ("Poll is finalized; no more votes.", status.HTTP_409_CONFLICT)
    if poll.status != PollStatus.ACTIVE or not (poll.start_at <= now <= poll.end_at):
        return ("Poll is not open for voting.", status.HTTP_409_CONFLICT)
    if session.used:
        return ("This link has already been used.", status.HTTP_409_CONFLICT)
    return None


def _render_ballot(request, poll, session, token, error, error_status):
    return render(
        request,
        "polls/vote.html",
        {"poll": poll, "session": session, "options": poll.options.all(), "token": token, "error": error},
        status=error_status,
    )


class PollByTokenView(views.APIView):
    """GET /poll/{token} — anonymous link landing: HTML ballot for browsers,
    JSON for API clients. One URL, dual render."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        session = AnonymousSession.objects.filter(token=token).select_related("poll").first()
        if session is None:
            if _wants_html(request):
                return render(request, "polls/error.html", {"heading": "Link not found", "message": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
            return Response({"detail": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
        poll = session.poll
        if session.is_expired or (session.expires_at and poll.end_at < timezone.now()):
            if _wants_html(request):
                return render(request, "polls/error.html", {"heading": "Link expired", "message": "This voting link has expired."}, status=status.HTTP_410_GONE)
            return Response({"detail": "This voting link has expired."}, status=status.HTTP_410_GONE)
        if _wants_html(request):
            if session.used:
                return redirect("poll-anon-confirm", token=token)
            return _render_ballot(request, poll, session, token, None, 200)
        return Response(
            {
                "poll": PollSerializer(poll, context={"request": request}).data,
                "session": {"id": str(session.id), "expires_at": session.expires_at, "used": session.used},
                "already_voted": Vote.objects.filter(poll=poll, fingerprint_hash__isnull=False).exists() if poll.is_anonymous else False,
            }
        )


class AnonymousVoteView(views.APIView):
    """POST /poll/{token}/vote — anonymous vote via one-time link.

    Dual mode: HTML form posts (browsers) redirect to the confirm page on
    success; JSON posts (API/HTMX) get the JSON contract below. Duplicate
    prevention is the existing one-vote-per-(poll, fingerprint_hash)
    constraint — no second dedupe path. The browser fingerprint is submitted
    by the frontend and stored as a SHA-256 hash; a used token is refused.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        session = AnonymousSession.objects.filter(token=token).select_related("poll").first()
        html = _is_form_post(request)
        if session is None:
            if html:
                return render(request, "polls/error.html", {"heading": "Link not found", "message": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
            return Response({"detail": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
        poll = session.poll
        err = _anon_vote_error(session, poll, timezone.now())
        if err is not None:
            if html:
                return _render_ballot(request, poll, session, token, err[0], err[1])
            return Response({"detail": err[0]}, status=err[1])

        if html:
            fingerprint = request.POST.get("fingerprint") or ""
            option_ids = request.POST.getlist("option_ids")
        else:
            fingerprint = request.data.get("fingerprint") or ""
            option_ids = request.data.get("option_ids")
        fingerprint_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest() if fingerprint else None
        if fingerprint_hash is None:
            msg = "Browser fingerprint is required for anonymous voting."
            if html:
                return _render_ballot(request, poll, session, token, msg, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        if Vote.objects.filter(poll=poll, fingerprint_hash=fingerprint_hash).exists():
            msg = "A vote with this browser already exists."
            if html:
                return _render_ballot(request, poll, session, token, msg, status.HTTP_409_CONFLICT)
            return Response({"detail": msg}, status=status.HTTP_409_CONFLICT)

        serializer = VoteSerializer(data={"option_ids": option_ids}, context={"poll": poll})
        if not serializer.is_valid():
            msg = "; ".join(str(e) for errs in serializer.errors.values() for e in errs)
            if html:
                return _render_ballot(request, poll, session, token, msg, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        option_ids = serializer.validated_data["option_ids"]
        with transaction.atomic():
            session.used = True
            session.fingerprint = fingerprint_hash
            session.save(update_fields=["used", "fingerprint"])
            vote = _cast_vote(poll, None, option_ids, fingerprint_hash=fingerprint_hash, anonymous_session=session)
        if html:
            return redirect("poll-anon-confirm", token=token)
        return Response(
            {
                "detail": "Vote recorded.",
                "confirm_url": f"/poll/{token}/confirm",
                "vote_id": str(vote.id),
            },
            status=status.HTTP_201_CREATED,
        )


class AnonymousConfirmView(views.APIView):
    """GET /poll/{token}/confirm — HTML confirmation page or JSON data."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        session = AnonymousSession.objects.filter(token=token).select_related("poll").first()
        if session is None:
            if _wants_html(request):
                return render(request, "polls/error.html", {"heading": "Link not found", "message": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
            return Response({"detail": "Invalid voting link."}, status=status.HTTP_404_NOT_FOUND)
        vote = session.votes.select_related("poll").first()
        if _wants_html(request):
            if vote is None and not session.used:
                return redirect("poll-by-token", token=token)
            return render(request, "polls/confirm.html", {"poll": session.poll, "vote": vote, "token": token})
        return Response(
            {
                "poll": PollSerializer(session.poll, context={"request": request}).data,
                "vote": VoteResultSerializer(vote).data if vote else None,
                "confirmed": vote is not None and vote.is_valid,
            }
        )


# ---------------- Authenticated user endpoints ----------------


class ActivePollsView(generics.ListAPIView):
    """GET /polls/active — polls an authenticated user can vote in."""

    serializer_class = PollSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        now = timezone.now()
        return (
            Poll.objects.filter(status=PollStatus.ACTIVE, start_at__lte=now, end_at__gte=now)
            .exclude(votes__user=self.request.user)
            .prefetch_related("options")
            .distinct()
        )


class PollDetailView(generics.RetrieveAPIView):
    serializer_class = PollSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Poll.objects.prefetch_related("options")

    def get(self, request, *args, **kwargs):
        poll = self.get_object()
        has_voted = request.user.is_authenticated and Vote.objects.filter(poll=poll, user=request.user).exists()
        return Response({"poll": self.get_serializer(poll).data, "has_voted": has_voted})


class AuthenticatedVoteView(views.APIView):
    """POST /polls/{id}/vote — vote in a non-anonymous poll."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        poll = generics.get_object_or_404(Poll, pk=pk)
        now = timezone.now()
        if poll.is_finalized:
            return Response({"detail": "Poll is finalized; no more votes."}, status=status.HTTP_409_CONFLICT)
        if poll.status != PollStatus.ACTIVE or not (poll.start_at <= now <= poll.end_at):
            return Response({"detail": "Poll is not open for voting."}, status=status.HTTP_409_CONFLICT)
        if poll.is_anonymous:
            return Response({"detail": "This poll uses anonymous links; use /poll/{token}/vote."}, status=status.HTTP_400_BAD_REQUEST)
        if Vote.objects.filter(poll=poll, user=request.user).exists():
            return Response({"detail": "You have already voted in this poll."}, status=status.HTTP_409_CONFLICT)

        serializer = VoteSerializer(data=request.data, context={"poll": poll})
        serializer.is_valid(raise_exception=True)
        option_ids = serializer.validated_data["option_ids"]
        with transaction.atomic():
            vote = _cast_vote(poll, request.user, option_ids)
        return Response(VoteResultSerializer(vote).data, status=status.HTTP_201_CREATED)


class MyVotesView(generics.ListAPIView):
    serializer_class = VoteResultSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Vote.objects.filter(user=self.request.user)
            .select_related("poll")
            .prefetch_related("options")
        )