from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Role, User
from audit.models import AuditLog
from audit.utils import compute_hash, verify_chain
from polls.models import AnonymousSession, Option, Poll, PollStatus, Vote


def client_post_json(client, url, payload):
    return client.post(url, payload, format="json")


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
    from audit.utils import log_event

    log_event("poll_created", "Poll", str(poll.id), {"title": poll.title, "is_anonymous": poll.is_anonymous}, created_by=created_by)
    return poll


class AuthTests(TestCase):
    def test_register_login_logout_flow(self):
        url = reverse("auth-register")
        resp = self.client.post(url, {"email": "alice@example.com", "password": "passw0rd!"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("access", resp.json())
        user = User.objects.get(email="alice@example.com")
        self.assertEqual(user.role.name, Role.Roles.USER)

        resp = self.client.post(reverse("auth-login"), {"email": "alice@example.com", "password": "passw0rd!"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        refresh = resp.json()["refresh"]

        auth = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['access']}"}
        resp = self.client.post(reverse("auth-logout"), {"refresh": refresh}, content_type="application/json", **auth)
        self.assertEqual(resp.status_code, 200)
        # Blacklisted refresh token is refused
        resp = self.client.post(reverse("token-refresh"), {"refresh": refresh}, content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_register_duplicate_email_rejected(self):
        self.client.post(reverse("auth-register"), {"email": "bob@example.com", "password": "passw0rd!"}, content_type="application/json")
        resp = self.client.post(reverse("auth-register"), {"email": "bob@example.com", "password": "passw0rd!"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_password_reset_no_email_leak(self):
        resp = self.client.post(reverse("auth-password-reset"), {"email": "nobody@example.com"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    def test_password_reset_confirm_changes_password(self):
        user = make_user("reset@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        resp = self.client.post(
            reverse("auth-password-reset-confirm"),
            {"uid": uid, "token": token, "new_password": "new-passw0rd!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        user.refresh_from_db()
        self.assertTrue(user.check_password("new-passw0rd!"))


class AdminPollTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.user = make_user("voter@example.com")
        self.client.force_authenticate(user=self.admin) if hasattr(self.client, "force_authenticate") else None

    def _auth(self, user):
        self.client = self.client.__class__()
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_admin_crud(self):
        self._auth(self.admin)
        resp = self.client.post(
            reverse("admin-poll-list"),
            {
                "title": "Board election",
                "description": "x",
                "is_anonymous": False,
                "allow_multiple_options": False,
                "end_at": (timezone.now() + timedelta(days=2)).isoformat(),
                "options": [{"text": "A", "order": 0}, {"text": "B", "order": 1}],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        poll_id = resp.json()["id"]
        self.assertEqual(Poll.objects.count(), 1)

        resp = self.client.get(reverse("admin-poll-detail", args=[poll_id]))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.patch(reverse("admin-poll-detail", args=[poll_id]), {"title": "Renamed"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Poll.objects.get(pk=poll_id).title, "Renamed")

        resp = self.client.delete(reverse("admin-poll-detail", args=[poll_id]))
        self.assertEqual(resp.status_code, 204)

    def test_non_admin_forbidden(self):
        self._auth(self.user)
        resp = self.client.get(reverse("admin-poll-list"))
        self.assertEqual(resp.status_code, 403)

    def test_status_update_is_applied(self):
        self._auth(self.admin)
        poll = make_poll(self.admin, status=PollStatus.DRAFT)
        resp = self.client.patch(reverse("admin-poll-detail", args=[poll.id]), {"status": "active"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        poll.refresh_from_db()
        self.assertEqual(poll.status, PollStatus.ACTIVE)

    def test_results_and_finalize(self):
        self._auth(self.admin)
        poll = make_poll(self.admin)
        resp = self.client.get(reverse("admin-poll-results", args=[poll.id]))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("tally", resp.json())

        resp = self.client.post(reverse("admin-poll-finalize", args=[poll.id]))
        self.assertEqual(resp.status_code, 200, resp.content)
        poll.refresh_from_db()
        self.assertIsNotNone(poll.finalized_at)

        # Finalized poll rejects votes and updates
        self._auth(self.user)
        resp = self.client.post(reverse("poll-vote", args=[poll.id]), {"option_ids": [str(poll.options.first().id)]}, format="json")
        self.assertEqual(resp.status_code, 409)
        self._auth(self.admin)
        resp = self.client.patch(reverse("admin-poll-detail", args=[poll.id]), {"title": "Nope"}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_change_user_role(self):
        self._auth(self.admin)
        secretariat = Role.objects.get(name=Role.Roles.SECRETARIAT)
        resp = self.client.post(reverse("admin-user-role", args=[self.user.id]), {"role_id": str(secretariat.id)}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role.name, Role.Roles.SECRETARIAT)


class VotingTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.user = make_user("voter@example.com")

    def _client(self, user=None):
        from rest_framework.test import APIClient

        c = APIClient()
        if user:
            c.force_authenticate(user=user)
        return c

    def test_authenticated_vote_once(self):
        poll = make_poll(self.admin)
        c = self._client(self.user)
        option = poll.options.first()
        resp = client_post_json(c, reverse("poll-vote", args=[poll.id]), {"option_ids": [str(option.id)]})
        self.assertEqual(resp.status_code, 201, resp.content)
        # Second vote refused
        resp = client_post_json(c, reverse("poll-vote", args=[poll.id]), {"option_ids": [str(option.id)]})
        self.assertEqual(resp.status_code, 409)
        # my-votes
        resp = c.get(reverse("my-votes"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 1)

    def test_active_polls_excludes_voted(self):
        poll = make_poll(self.admin)
        c = self._client(self.user)
        client_post_json(c, reverse("poll-vote", args=[poll.id]), {"option_ids": [str(poll.options.first().id)]})
        resp = c.get(reverse("polls-active"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_multiple_options_validation(self):
        poll = make_poll(self.admin, is_anonymous=False)
        poll.allow_multiple_options = False
        poll.save()
        c = self._client(self.user)
        resp = client_post_json(c, reverse("poll-vote", args=[poll.id]), {"option_ids": [str(o.id) for o in poll.options.all()]})
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_link_voting(self):
        poll = make_poll(self.admin, is_anonymous=True)
        session = AnonymousSession.objects.create_session(poll)
        c = self._client()
        resp = c.get(reverse("poll-by-token", args=[session.token]))
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = client_post_json(
            c,
            reverse("poll-anon-vote", args=[session.token]),
            {"option_ids": [str(poll.options.first().id)], "fingerprint": "fp-browser-abc"},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        session.refresh_from_db()
        self.assertTrue(session.used)

        # Same link cannot vote twice
        resp = client_post_json(
            c,
            reverse("poll-anon-vote", args=[session.token]),
            {"option_ids": [str(poll.options.all()[1].id)], "fingerprint": "fp-browser-abc"},
        )
        self.assertEqual(resp.status_code, 409)

        # Confirm page
        resp = c.get(reverse("poll-anon-confirm", args=[session.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["confirmed"])

    def test_anonymous_fingerprint_dedupe(self):
        poll = make_poll(self.admin, is_anonymous=True)
        s1 = AnonymousSession.objects.create_session(poll)
        s2 = AnonymousSession.objects.create_session(poll)
        c = self._client()
        resp = client_post_json(c, reverse("poll-anon-vote", args=[s1.token]), {"option_ids": [str(poll.options.first().id)], "fingerprint": "same-browser"})
        self.assertEqual(resp.status_code, 201)
        # Same fingerprint, different link: refused
        resp = client_post_json(c, reverse("poll-anon-vote", args=[s2.token]), {"option_ids": [str(poll.options.first().id)], "fingerprint": "same-browser"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Vote.objects.filter(poll=poll).count(), 1)

    def test_expired_link_rejected(self):
        poll = make_poll(self.admin, is_anonymous=True)
        session = AnonymousSession.objects.create_session(poll)
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save()
        c = self._client()
        resp = client_post_json(c, reverse("poll-anon-vote", args=[session.token]), {"option_ids": [str(poll.options.first().id)], "fingerprint": "fp"})
        self.assertEqual(resp.status_code, 410)

    def test_anonymous_vote_without_fingerprint_allowed(self):
        """A client without crypto.subtle (plain HTTP) omits the fingerprint —
        the one-time link alone must guarantee uniqueness."""
        poll = make_poll(self.admin, is_anonymous=True)
        s1 = AnonymousSession.objects.create_session(poll)
        s2 = AnonymousSession.objects.create_session(poll)
        c = self._client()
        resp = client_post_json(c, reverse("poll-anon-vote", args=[s1.token]), {"option_ids": [str(poll.options.first().id)]})
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = client_post_json(c, reverse("poll-anon-vote", args=[s2.token]), {"option_ids": [str(poll.options.all()[1].id)]})
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_identified_vote_requires_vote_permission(self):
        """Self-registered users vote; a user whose role lacks `vote` is 403."""
        poll = make_poll(self.admin)
        no_vote_role, _ = Role.objects.get_or_create(name="Observer", defaults={"permissions": []})
        self.user.role = no_vote_role
        self.user.save(update_fields=["role"])
        c = self._client(self.user)
        resp = client_post_json(c, reverse("poll-vote", args=[poll.id]), {"option_ids": [str(poll.options.first().id)]})
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_generate_link_ttl_hours_validated(self):
        poll = make_poll(self.admin, is_anonymous=True)
        c = self._client(self.admin)
        resp = client_post_json(c, reverse("admin-generate-link", args=[poll.id]), {"ttl_hours": "abc"})
        self.assertEqual(resp.status_code, 400, resp.content)
        resp = client_post_json(c, reverse("admin-generate-link", args=[poll.id]), {"ttl_hours": 0})
        self.assertEqual(resp.status_code, 400, resp.content)


class AuditChainTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)

    def test_chain_forms_and_verifies(self):
        poll = make_poll(self.admin)
        user = make_user("voter@example.com")
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user=user)
        c.post(reverse("poll-vote", args=[poll.id]), {"option_ids": [str(poll.options.first().id)]}, format="json")
        ok, problems = verify_chain()
        self.assertTrue(ok, problems)
        self.assertGreaterEqual(AuditLog.objects.count(), 2)  # poll_created + vote_cast

    def test_tampering_detected(self):
        make_poll(self.admin)
        entry = AuditLog.objects.order_by("sequence").first()
        # Direct DB-level tamper (bypass ORM protections)
        from django.db import connection

        with connection.cursor() as cur:
            if connection.vendor == "sqlite":
                cur.execute("UPDATE audit_auditlog SET data = ? WHERE sequence = ?", ['{"evil": true}', entry.sequence])
            else:
                cur.execute("UPDATE audit_auditlog SET data = %s WHERE sequence = %s", ['{"evil": true}', entry.sequence])
        ok, problems = verify_chain()
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in p for p in problems))

    def test_orm_immutable(self):
        make_poll(self.admin)
        entry = AuditLog.objects.order_by("sequence").first()
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.update(data={})

    def test_hash_function_deterministic(self):
        h1 = compute_hash("a" * 64, {"k": 1})
        h2 = compute_hash("a" * 64, {"k": 1})
        h3 = compute_hash("b" * 64, {"k": 1})
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)

    def test_ballot_secrecy_invariant(self):
        """The full audit chain must not reveal how any individual voted:
        no vote ids, no option ids in any audit payload; the confirm JSON
        must not return ballot contents."""
        poll = make_poll(self.admin, is_anonymous=True)
        s1 = AnonymousSession.objects.create_session(poll)
        s2 = AnonymousSession.objects.create_session(poll)
        from rest_framework.test import APIClient

        c = APIClient()
        # two anonymous votes with different choices
        c.post(reverse("poll-anon-vote", args=[s1.token]), {"option_ids": [str(poll.options.first().id)], "fingerprint": "fp-a"}, format="json")
        c.post(reverse("poll-anon-vote", args=[s2.token]), {"option_ids": [str(poll.options.all()[1].id)], "fingerprint": "fp-b"}, format="json")
        vote_ids = set(str(v.id) for v in Vote.objects.all())
        option_ids = set(str(o.id) for o in poll.options.all())
        for entry in AuditLog.objects.all():
            blob = str(entry.data)
            for vid in vote_ids:
                self.assertNotIn(vid, blob, f"vote id leaked in {entry.event_type}")
            for oid in option_ids:
                self.assertNotIn(oid, blob, f"option id leaked in {entry.event_type}")
        # confirm JSON: no ballot contents
        resp = c.get(reverse("poll-anon-confirm", args=[s1.token]))
        payload = resp.json()
        self.assertTrue(payload["confirmed"])
        self.assertNotIn("vote", payload)
        self.assertNotIn("options", payload)
