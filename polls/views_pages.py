"""Server-rendered HTML pages (HTMX + Alpine.js frontend).

Thin views over the same serializers / permission classes the JSON API uses.
Public anonymous voting (landing/ballot/confirm/results) lives in
views_public.py as dual-mode API views; this module holds the results page
and the session-auth admin panel, all gated server-side by Role permissions.
"""

from django import forms
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Role
from audit.utils import audit_trail, log_event, verify_chain
from .models import AnonymousSession, Option, Poll, PollStatus
from .serializers import PollCreateSerializer, PollUpdateSerializer


def _can_view_results(user):
    return bool(user and user.is_authenticated and (user.has_permission("view_results") or user.has_permission("create_poll")))


def _login_redirect(request):
    return redirect("panel-login")


# ---------------- Public results page ----------------


@require_GET
def poll_results(request, poll_id):
    """GET /polls/<id>/results/ — results page; only for closed polls."""
    poll = get_object_or_404(Poll.objects.prefetch_related("options"), pk=poll_id)
    if not poll.is_finalized and poll.status != PollStatus.CLOSED:
        return render(request, "polls/error.html", {"heading": _("Not available"), "message": _("Results are available after the poll closes.")}, status=403)
    tally = _tally_with_percentages(poll)
    return render(
        request,
        "polls/results.html",
        {"poll": poll, "tally": tally, "total_valid_votes": poll.votes.filter(is_valid=True).count(), "finalized": poll.is_finalized},
    )


# ---------------- Admin panel (session auth) ----------------


def _panel_gate(request):
    """Server-side Role check; never trust the template to hide links."""
    return request.user.is_authenticated and request.user.has_permission("create_poll")


@require_GET
def panel_login_page(request):
    if _can_view_results(request.user):
        return redirect("panel-dashboard")
    return render(request, "panel/login.html", {"error": None})


def panel_login(request):
    if request.method == "GET":
        return panel_login_page(request)
    email = (request.POST.get("email") or "").lower().strip()
    password = request.POST.get("password") or ""
    user = authenticate(request, email=email, password=password)
    if user is None or not _can_view_results(user):
        return render(request, "panel/login.html", {"error": _("Invalid credentials or insufficient role.")}, status=401)
    login(request, user)
    return redirect("panel-dashboard")


def panel_logout(request):
    logout(request)
    return redirect("panel-login")


class PollForm(forms.Form):
    title = forms.CharField(max_length=255)
    description = forms.CharField(required=False, widget=forms.Textarea)
    is_anonymous = forms.BooleanField(required=False)
    allow_multiple_options = forms.BooleanField(required=False)
    start_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    end_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    options_text = forms.CharField(widget=forms.Textarea, help_text=_("One option per line."))
    status = forms.ChoiceField(choices=[(PollStatus.DRAFT, PollStatus.DRAFT.label), (PollStatus.ACTIVE, PollStatus.ACTIVE.label)], initial=PollStatus.DRAFT)

    def clean_options_text(self):
        lines = [ln.strip() for ln in (self.cleaned_data["options_text"] or "").splitlines() if ln.strip()]
        if len(lines) < 2:
            raise forms.ValidationError(_("A poll needs at least two options."))
        return lines

    def clean(self):
        cleaned = super().clean()
        start_at, end_at = cleaned.get("start_at"), cleaned.get("end_at")
        if start_at and end_at and end_at <= start_at:
            self.add_error("end_at", _("Closing time must be after opening time."))
        return cleaned


def _tally_with_percentages(poll):
    tally = list(poll.options.annotate(n=Count("votes", filter=Q(votes__is_valid=True))).values("id", "text", "order", "n"))
    selections = sum(row["n"] for row in tally)
    for row in tally:
        row["percent"] = round((row["n"] / selections) * 100, 1) if selections else 0
    return tally


def _poll_form_initial(poll):
    return {
        "title": poll.title,
        "description": poll.description,
        "is_anonymous": poll.is_anonymous,
        "allow_multiple_options": poll.allow_multiple_options,
        "start_at": poll.start_at,
        "end_at": poll.end_at,
        "options_text": "\n".join(o.text for o in poll.options.all()),
        "status": poll.status if poll.status in ("draft", "active") else "active",
    }


@require_GET
def panel_dashboard(request):
    """GET /panel/ — poll CRUD overview, role management link, audit indicator."""
    if not _can_view_results(request.user):
        return _login_redirect(request)
    polls = Poll.objects.prefetch_related("options").annotate(
        vote_count=Count("votes", distinct=True),
        link_count=Count("anonymous_sessions", distinct=True),
    )
    ok, problems = verify_chain()
    return render(request, "panel/dashboard.html", {
        "polls": polls,
        "chain_ok": ok,
        "chain_problems": problems[:5],
        "can_manage": _panel_gate(request),
        "stats": {
            "total": polls.count(),
            "active": polls.filter(status=PollStatus.ACTIVE).count(),
            "votes": sum(p.vote_count for p in polls),
        },
        "active_tab": "polls",
    })


@require_GET
def panel_poll_new(request):
    if not _panel_gate(request):
        return _login_redirect(request)
    return render(request, "panel/poll_form.html", {"form": PollForm(), "poll": None, "error": None})


@require_POST
def panel_poll_create(request):
    if not _panel_gate(request):
        return _login_redirect(request)
    form = PollForm(request.POST)
    if form.is_valid():
        lines = form.cleaned_data["options_text"]
        payload = {
            "title": form.cleaned_data["title"],
            "description": form.cleaned_data["description"],
            "is_anonymous": form.cleaned_data["is_anonymous"],
            "allow_multiple_options": form.cleaned_data["allow_multiple_options"],
            "start_at": form.cleaned_data["start_at"].isoformat(),
            "end_at": form.cleaned_data["end_at"].isoformat(),
            "options": [{"text": t, "order": i} for i, t in enumerate(lines)],
        }
        serializer = PollCreateSerializer(data=payload)
        if serializer.is_valid():
            with transaction.atomic():
                poll = serializer.save(created_by=request.user, status=form.cleaned_data["status"])
                log_event("poll_created", "Poll", str(poll.id), {"title": poll.title, "is_anonymous": poll.is_anonymous}, created_by=request.user)
            return redirect("panel-dashboard")
    return render(request, "panel/poll_form.html", {"form": form, "poll": None, "error": _("Check the form fields.")}, status=400)


@require_GET
def panel_poll_edit(request, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if not _panel_gate(request):
        return _login_redirect(request)
    if poll.is_finalized:
        return redirect("panel-dashboard")
    return render(request, "panel/poll_form.html", {"form": PollForm(initial=_poll_form_initial(poll)), "poll": poll, "error": None})


@require_POST
def panel_poll_update(request, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if not _panel_gate(request):
        return _login_redirect(request)
    if poll.is_finalized:
        return render(request, "polls/error.html", {"heading": _("Immutable"), "message": _("Poll is finalized and immutable.")}, status=409)
    form = PollForm(request.POST)
    if form.is_valid():
        lines = form.cleaned_data["options_text"]
        current_lines = [o.text for o in poll.options.all()]
        if poll.votes.exists():
            if current_lines != lines:
                form.add_error("options_text", _("Options cannot change after votes have been cast."))
            if form.cleaned_data["is_anonymous"] != poll.is_anonymous:
                form.add_error("is_anonymous", _("Voting mode cannot change after votes have been cast."))
            if form.cleaned_data["allow_multiple_options"] != poll.allow_multiple_options:
                form.add_error("allow_multiple_options", _("Selection rules cannot change after votes have been cast."))
            if form.errors:
                return render(request, "panel/poll_form.html", {"form": form, "poll": poll, "error": _("Check the form fields.")}, status=400)
        if poll.anonymous_sessions.exists() and form.cleaned_data["is_anonymous"] != poll.is_anonymous:
            form.add_error("is_anonymous", _("Voting mode cannot change after anonymous links have been generated."))
            return render(request, "panel/poll_form.html", {"form": form, "poll": poll, "error": _("Check the form fields.")}, status=400)
        data = {
            "title": form.cleaned_data["title"],
            "description": form.cleaned_data["description"],
            "is_anonymous": form.cleaned_data["is_anonymous"],
            "allow_multiple_options": form.cleaned_data["allow_multiple_options"],
            "start_at": form.cleaned_data["start_at"].isoformat(),
            "end_at": form.cleaned_data["end_at"].isoformat(),
            "status": form.cleaned_data["status"],
        }
        serializer = PollUpdateSerializer(poll, data=data, partial=True)
        if serializer.is_valid():
            with transaction.atomic():
                serializer.save()
                if current_lines != lines:
                    Option.objects.filter(poll=poll).delete()
                    Option.objects.bulk_create([Option(poll=poll, text=t, order=i) for i, t in enumerate(lines)])
                log_event("poll_updated", "Poll", str(poll.id), {"fields": sorted(data.keys())}, created_by=request.user)
            return redirect("panel-dashboard")
        for field, errors in serializer.errors.items():
            target = field if field in form.fields else None
            for error in errors:
                form.add_error(target, error)
    return render(request, "panel/poll_form.html", {"form": form, "poll": poll, "error": _("Check the form fields.")}, status=400)


@require_POST
def panel_poll_finalize(request, poll_id):
    if not _panel_gate(request):
        return _login_redirect(request)
    with transaction.atomic():
        poll = get_object_or_404(Poll.objects.select_for_update(), pk=poll_id)
        if poll.is_finalized:
            return redirect("panel-dashboard")
        poll.status = PollStatus.CLOSED
        poll.finalized_at = timezone.now()
        poll.save(update_fields=["status", "finalized_at"])
        tally = list(poll.options.annotate(n=Count("votes", filter=Q(votes__is_valid=True))).values("id", "text", "order", "n"))
        log_event("result_finalized", "Poll", str(poll.id), {"status": "closed", "tally": tally, "finalized_at": poll.finalized_at.isoformat()}, created_by=request.user)
    return redirect("panel-dashboard")


@require_POST
def panel_generate_link(request, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if not _panel_gate(request):
        return _login_redirect(request)
    if not poll.is_anonymous:
        return render(request, "polls/error.html", {"heading": _("Not anonymous"), "message": _("Links can only be generated for anonymous polls.")}, status=400)
    if poll.is_finalized or not poll.is_open:
        return render(request, "polls/error.html", {"heading": _("Voting unavailable"), "message": _("Links can only be generated while the poll is open.")}, status=409)
    session = AnonymousSession.objects.create_session(poll, ttl_hours=None)
    log_event("session_generated", "Poll", str(poll.id), {"session_id": str(session.id), "expires_at": session.expires_at.isoformat()}, created_by=request.user)
    vote_url = request.build_absolute_uri(reverse("poll-by-token", args=[session.token]))
    return render(request, "panel/link.html", {"poll": poll, "session": session, "vote_url": vote_url})


@require_GET
def panel_poll_results(request, poll_id):
    """Results with tallies + audit trail (Admin or Secretariat view_results)."""
    poll = get_object_or_404(Poll.objects.prefetch_related("options"), pk=poll_id)
    if not _can_view_results(request.user):
        return _login_redirect(request)
    tally = _tally_with_percentages(poll)
    trail = audit_trail(entity_type="Poll", entity_id=poll.id)
    return render(request, "panel/results.html", {
        "poll": poll, "tally": tally, "total_valid_votes": poll.votes.filter(is_valid=True).count(),
        "audit_trail": trail, "finalized": poll.is_finalized, "can_manage": _panel_gate(request),
    })


@require_POST
def panel_poll_delete(request, poll_id):
    if not _panel_gate(request):
        return _login_redirect(request)
    poll = get_object_or_404(Poll, pk=poll_id)
    if poll.is_finalized or poll.votes.exists():
        return render(request, "polls/error.html", {"heading": _("Cannot delete"), "message": _("Poll with votes or finalized results cannot be deleted.")}, status=409)
    log_event("poll_updated", "Poll", str(poll.id), {"deleted": True, "title": poll.title}, created_by=request.user)
    poll.delete()
    return redirect("panel-dashboard")


@require_GET
def panel_users(request):
    """Role management list."""
    if not _panel_gate(request):
        return _login_redirect(request)
    User = get_user_model()
    users = User.objects.select_related("role").order_by("email")
    return render(request, "panel/users.html", {"users": users, "roles": Role.objects.all(), "active_tab": "users"})


@require_POST
def panel_user_role(request, user_id):
    if not _panel_gate(request):
        return _login_redirect(request)
    User = get_user_model()
    target = get_object_or_404(User, pk=user_id)
    role = get_object_or_404(Role, pk=request.POST.get("role_id"))
    old_role = target.role.name if target.role else None
    target.role = role
    target.save(update_fields=["role"])
    log_event("role_changed", "User", str(target.id), {"from": old_role, "to": role.name}, created_by=request.user)
    return redirect("panel-users")
