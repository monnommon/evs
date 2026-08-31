"""Frontend page tests: rendered HTML pages (HTMX/Alpine layer) for evs-005/006.

Covers the anonymous link flow end-to-end (landing → vote POST → confirm),
closed-poll public results, and the admin panel (session auth + server-side
role checks, audit-verify indicator, link generation, role management).
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from audit.models import AuditLog
from polls.models import AnonymousSession, Option, Poll, PollStatus, Vote


def make_user(email, role_name=Role.Roles.USER, password="passw0rd!"):
    Role.ensure_defaults()
    return User.objects.create_user(email=email, password=password, role=Role.objects.get(name=role_name))


def make_poll(created_by, is_anonymous=False, status=PollStatus.ACTIVE, with_options=True):
    poll = Poll.objects.create(
        title="Test Poll",
        description="d",
        created_by=created_by,
        is_anonymous=is_anonymous,
        end_at=timezone.now() + timedelta(days=1),
        status=status,
    )
    if with_options:
        poll.options.create(text="Alpha", order=0)
        poll.options.create(text="Beta", order=1)
    return poll


HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


class AnonymousFlowPageTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.poll = make_poll(self.admin, is_anonymous=True)
        self.session = AnonymousSession.objects.create_session(self.poll)

    def test_landing_renders_ballot(self):
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "polls/vote.html")
        self.assertContains(resp, "Test Poll", status_code=200)
        self.assertContains(resp, "Cast vote")
        self.assertEqual(resp.context["token"], self.session.token)
        # ballot form targets the form POST endpoint
        self.assertContains(resp, f'action="/poll/{self.session.token}/vote/"')

    def test_landing_json_still_works(self):
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("poll", resp.json())

    def test_vote_submit_redirects_to_confirm(self):
        option = self.poll.options.first()
        resp = self.client.post(
            reverse("poll-anon-vote", args=[self.session.token]),
            {"option_ids": [str(option.id)], "fingerprint": "fp-browser-abc"},
        )
        self.assertEqual(resp.status_code, 302, resp.content)
        self.assertTrue(resp.url.endswith(f"/poll/{self.session.token}/confirm/"))
        self.session.refresh_from_db()
        self.assertTrue(self.session.used)
        self.assertEqual(Vote.objects.filter(poll=self.poll).count(), 1)
        # audit chain entry appended
        self.assertTrue(AuditLog.objects.filter(event_type="anonymous_vote_cast").exists())

    def test_confirm_page_shows_recorded_vote(self):
        option = self.poll.options.first()
        self.client.post(reverse("poll-anon-vote", args=[self.session.token]),
                         {"option_ids": [str(option.id)], "fingerprint": "fp-browser-abc"})
        resp = self.client.get(reverse("poll-anon-confirm", args=[self.session.token]), **HTML)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "polls/confirm.html")
        self.assertContains(resp, "Vote confirmed")
        self.assertContains(resp, "sealed in the audit chain")

    def test_used_link_redirects_landing_to_confirm(self):
        option = self.poll.options.first()
        self.client.post(reverse("poll-anon-vote", args=[self.session.token]),
                         {"option_ids": [str(option.id)], "fingerprint": "fp1"})
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.endswith("/confirm/"))

    def test_fingerprint_dedupe_shows_error_on_ballot(self):
        s2 = AnonymousSession.objects.create_session(self.poll)
        self.client.post(reverse("poll-anon-vote", args=[s2.token]),
                         {"option_ids": [str(self.poll.options.first().id)], "fingerprint": "same-browser"})
        resp = self.client.post(
            reverse("poll-anon-vote", args=[self.session.token]),
            {"option_ids": [str(self.poll.options.first().id)], "fingerprint": "same-browser"},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "A vote with this browser already exists.", status_code=409)
        self.assertEqual(Vote.objects.filter(poll=self.poll).count(), 1)

    def test_bad_token_shows_error_page(self):
        resp = self.client.get("/poll/no-such-token/", **HTML)
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "polls/error.html")
        self.assertContains(resp, "Invalid voting link.", status_code=404)

    def test_expired_link_shows_error_page(self):
        self.session.expires_at = timezone.now() - timedelta(minutes=1)
        self.session.save()
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertEqual(resp.status_code, 410)
        self.assertContains(resp, "expired", status_code=410)


class PublicResultsPageTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.poll = make_poll(self.admin)

    def test_active_poll_results_hidden(self):
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "after the poll closes", status_code=403)

    def test_closed_poll_results_render(self):
        self.poll.status = PollStatus.CLOSED
        self.poll.save()
        option = self.poll.options.first()
        Vote.objects.create(poll=self.poll)
        vote = Vote.objects.first()
        vote.options.set([option])
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "polls/results.html")
        self.assertContains(resp, "Alpha")
        self.assertContains(resp, "Total valid votes: 1")

    def test_finalized_poll_results_render_with_banner(self):
        self.poll.status = PollStatus.CLOSED
        self.poll.finalized_at = timezone.now()
        self.poll.save()
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]))
        self.assertContains(resp, "Results finalized", status_code=200)
        self.assertContains(resp, 'data-testid="finalized-banner"')


class AdminPanelPageTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.secretariat = make_user("sec@example.com", Role.Roles.SECRETARIAT)
        self.user = make_user("voter@example.com")
        self.poll = make_poll(self.admin, is_anonymous=True)

    def login(self, email="admin@example.com", password="passw0rd!"):
        ok = self.client.login(email=email, password=password)
        self.assertTrue(ok)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("panel-dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/panel/login/", resp.url)

    def test_non_admin_forbidden_from_panel(self):
        self.client.login(email="voter@example.com", password="passw0rd!")
        resp = self.client.get(reverse("panel-dashboard"))
        self.assertIn(resp.status_code, (302, 403))

    def test_login_page_renders(self):
        resp = self.client.get(reverse("panel-login"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/login.html")
        self.assertContains(resp, "Admin panel")

    def test_dashboard_renders_polls_and_audit_indicator(self):
        self.login()
        resp = self.client.get(reverse("panel-dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/dashboard.html")
        self.assertContains(resp, "Test Poll")
        self.assertContains(resp, 'data-testid="audit-indicator"')
        self.assertContains(resp, "Audit chain verified")

    def test_dashboard_shows_broken_chain(self):
        self.login()
        entry = AuditLog.objects.order_by("sequence").first()
        if entry is not None:
            from django.db import connection

            with connection.cursor() as cur:
                if connection.vendor == "sqlite":
                    cur.execute("UPDATE audit_auditlog SET data = ? WHERE sequence = ?", ['{"evil": true}', entry.sequence])
                else:
                    cur.execute("UPDATE audit_auditlog SET data = %s WHERE sequence = %s", ['{"evil": true}', entry.sequence])
            resp = self.client.get(reverse("panel-dashboard"))
            self.assertContains(resp, "BROKEN", status_code=200)

    def test_create_poll_via_form(self):
        self.login()
        resp = self.client.post(
            reverse("panel-poll-create"),
            {
                "title": "Board election",
                "description": "x",
                "start_at": "2026-09-01 10:00",
                "end_at": "2026-09-02 10:00",
                "options_text": "Alice\nBob",
                "status": "active",
            },
        )
        self.assertEqual(resp.status_code, 302, resp.content)
        poll = Poll.objects.get(title="Board election")
        self.assertEqual(poll.options.count(), 2)
        self.assertTrue(AuditLog.objects.filter(event_type="poll_created", entity_id=str(poll.id)).exists())

    def test_generate_link_page(self):
        self.login()
        resp = self.client.post(reverse("panel-generate-link", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTemplateUsed(resp, "panel/link.html")
        session = self.poll.anonymous_sessions.first()
        self.assertIsNotNone(session)
        self.assertContains(resp, f"/poll/{session.token}/")

    def test_finalize_then_results_page(self):
        self.login()
        resp = self.client.post(reverse("panel-poll-finalize", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 302, resp.content)
        self.poll.refresh_from_db()
        self.assertIsNotNone(self.poll.finalized_at)
        self.assertTrue(AuditLog.objects.filter(event_type="result_finalized", entity_id=str(self.poll.id)).exists())
        resp = self.client.get(reverse("panel-poll-results", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/results.html")
        self.assertContains(resp, "Audit trail")
        self.assertContains(resp, "result_finalized")

    def test_secretariat_can_view_results_not_dashboard(self):
        self.client.login(email="sec@example.com", password="passw0rd!")
        resp = self.client.get(reverse("panel-poll-results", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("panel-dashboard"))
        self.assertIn(resp.status_code, (302, 403))

    def test_role_management_page_and_change(self):
        self.login()
        resp = self.client.get(reverse("panel-users"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/users.html")
        self.assertContains(resp, "voter@example.com")
        new_role = Role.objects.get(name=Role.Roles.SECRETARIAT)
        resp = self.client.post(reverse("panel-user-role", args=[self.user.id]), {"role_id": str(new_role.id)})
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role.name, Role.Roles.SECRETARIAT)
        self.assertTrue(AuditLog.objects.filter(event_type="role_changed", entity_id=str(self.user.id)).exists())

    def test_poll_edit_page_renders(self):
        self.login()
        resp = self.client.get(reverse("panel-poll-edit", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/poll_form.html")
        self.assertContains(resp, "Edit poll")
        self.assertContains(resp, "Alpha")
    def test_secretariat_can_login_via_login_view(self):
        """Regression: the login VIEW (not client.login) must accept Secretariat."""
        resp = self.client.post(
            reverse("panel-login"), {"email": "sec@example.com", "password": "passw0rd!"}
        )
        self.assertEqual(resp.status_code, 302)
        self.client.get(resp.url)  # follow redirect
        resp = self.client.get(reverse("panel-poll-results", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("panel-dashboard"))
        self.assertIn(resp.status_code, (302, 403))

    def test_regular_user_rejected_at_login_view(self):
        resp = self.client.post(
            reverse("panel-login"), {"email": "voter@example.com", "password": "passw0rd!"}
        )
        self.assertEqual(resp.status_code, 401)
