"""Phase 3–5 regression tests: landing, dashboard filter/pagination,
bulk links CSV, results export CSV, results_visibility, poll lifecycle
command, registration switch, multi-choice percentages."""

import csv
import io
import re
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from polls.models import AnonymousSession, Poll, PollStatus

from .tests_frontend import HTML, make_poll, make_user


class LandingTests(TestCase):
    def test_root_lands_for_browsers(self):
        resp = self.client.get("/", **HTML)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "polls/landing.html")

    def test_root_json_redirects_to_panel(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/panel/")


class DashboardFilterTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.client.login(email="admin@example.com", password="passw0rd!")

    def test_edit_form_preserves_dates(self):
        """datetime-local inputs need value="YYYY-MM-DDTHH:MM" — the Django
        default "YYYY-MM-DD HH:MM:SS" makes browsers drop the value entirely
        (the 'form loses saved data' bug)."""
        from polls.views_pages import PollForm, _poll_form_initial

        poll = make_poll(self.admin)
        form = PollForm(initial=_poll_form_initial(poll))
        for name in ("start_at", "end_at"):
            html = str(form[name])
            m = re.search(r'value="([^"]+)"', html)
            self.assertIsNotNone(m, f"{name} renders no value")
            self.assertRegex(m.group(1), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", f"{name} not datetime-local format: {m.group(1)}")

    def test_status_filter(self):
        make_poll(self.admin, status=PollStatus.CLOSED)
        resp = self.client.get(reverse("panel-dashboard"), {"status": "closed"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "badge-closed")
        resp = self.client.get(reverse("panel-dashboard"), {"status": "active"})
        for row in resp.context["polls"]:
            self.assertEqual(row.status, PollStatus.ACTIVE)

    def test_invalid_status_ignored(self):
        make_poll(self.admin)
        resp = self.client.get(reverse("panel-dashboard"), {"status": "bogus"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test Poll")


class BulkLinkTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.poll = make_poll(self.admin, is_anonymous=True)
        self.client.login(email="admin@example.com", password="passw0rd!")

    def test_single_link_still_renders_page(self):
        resp = self.client.post(reverse("panel-generate-link", args=[self.poll.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "panel/link.html")

    def test_bulk_returns_csv(self):
        resp = self.client.post(reverse("panel-generate-link", args=[self.poll.id]), {"count": 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        self.assertEqual(len(rows), 6)  # header + 5
        self.assertEqual(rows[0], ["token", "url", "expires_at"])
        self.assertEqual(self.poll.anonymous_sessions.count(), 5)

    def test_count_clamped(self):
        self.client.post(reverse("panel-generate-link", args=[self.poll.id]), {"count": 9999})
        self.assertEqual(self.poll.anonymous_sessions.count(), 500)
        self.client.post(reverse("panel-generate-link", args=[self.poll.id]), {"count": "garbage"})
        self.assertEqual(self.poll.anonymous_sessions.count(), 501)


class ResultsVisibilityTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.poll = make_poll(self.admin, status=PollStatus.CLOSED)
        self.poll.finalized_at = timezone.now()
        self.poll.save()

    def test_public_results_visible(self):
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]), **HTML)
        self.assertEqual(resp.status_code, 200)

    def test_hidden_results_403_for_anonymous(self):
        self.poll.results_visibility = "hidden"
        self.poll.save()
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]), **HTML)
        self.assertEqual(resp.status_code, 403)

    def test_hidden_results_visible_to_admin(self):
        self.poll.results_visibility = "hidden"
        self.poll.save()
        self.client.login(email="admin@example.com", password="passw0rd!")
        resp = self.client.get(reverse("page-poll-results", args=[self.poll.id]), **HTML)
        self.assertEqual(resp.status_code, 200)


class ResultsExportTests(TestCase):
    def test_export_csv_gated(self):
        admin = make_user("admin@example.com", Role.Roles.ADMIN)
        poll = make_poll(admin, status=PollStatus.CLOSED)
        resp = self.client.get(reverse("panel-poll-results-export", args=[poll.id]))
        self.assertEqual(resp.status_code, 302)  # → login
        self.client.login(email="admin@example.com", password="passw0rd!")
        resp = self.client.get(reverse("panel-poll-results-export", args=[poll.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("percent_of_voters", resp.content.decode())


class PollLifecycleTests(TestCase):
    def test_opens_and_closes_by_schedule(self):
        admin = make_user("admin@example.com", Role.Roles.ADMIN)
        now = timezone.now()
        due = Poll.objects.create(title="due", created_by=admin, start_at=now - timedelta(minutes=1), end_at=now + timedelta(days=1), status=PollStatus.DRAFT)
        expired = Poll.objects.create(title="expired", created_by=admin, start_at=now - timedelta(days=2), end_at=now - timedelta(minutes=1), status=PollStatus.ACTIVE)
        out = io.StringIO()
        call_command("poll_lifecycle", stdout=out)
        due.refresh_from_db(); expired.refresh_from_db()
        self.assertEqual(due.status, PollStatus.ACTIVE)
        self.assertEqual(expired.status, PollStatus.CLOSED)


class RegistrationSwitchTests(TestCase):
    def test_registration_closed(self):
        with self.settings(REGISTRATION_OPEN=False):
            resp = self.client.post(reverse("auth-register"), {"email": "x@example.com", "password": "passw0rd!"}, content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())


class MultiChoicePercentTests(TestCase):
    def test_percent_of_voters_not_selections(self):
        from polls.views_pages import _tally_with_percentages

        admin = make_user("admin@example.com", Role.Roles.ADMIN)
        poll = make_poll(admin, is_anonymous=False, with_options=False)
        poll.allow_multiple_options = True
        poll.save()
        a = poll.options.create(text="A", order=0)
        b = poll.options.create(text="B", order=1)
        from polls.models import Vote

        v1 = Vote.objects.create(poll=poll, user=admin)
        v1.options.set([a, b])
        voter2 = make_user("voter@example.com")
        v2 = Vote.objects.create(poll=poll, user=voter2)
        v2.options.set([a])
        tally = _tally_with_percentages(poll)
        by_text = {row["text"]: row for row in tally}
        self.assertEqual(by_text["A"]["percent"], 100.0)  # 2/2 voters
        self.assertEqual(by_text["B"]["percent"], 50.0)  # 1/2 voters