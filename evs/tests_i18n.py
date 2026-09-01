"""Tests for evs-010 (root redirect) and evs-011 (RU/EN i18n + switcher).

Root redirect: GET / 302s to /panel/ (only the bare root; JSON/API paths
untouched). i18n: LocaleMiddleware + cookie persistence, the RU|EN switcher
on every page, and translated strings on the anonymous voting landing.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate, deactivate

from accounts.models import Role, User
from polls.models import AnonymousSession, Poll, PollStatus

from .tests_frontend import HTML, make_poll, make_user


class RootRedirectTests(TestCase):
    def test_root_redirects_to_panel(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/panel/")

    def test_authenticated_root_lands_on_dashboard(self):
        make_user("admin@example.com", Role.Roles.ADMIN)
        self.client.login(email="admin@example.com", password="passw0rd!")
        resp = self.client.get("/")
        self.assertEqual(resp["Location"], "/panel/")
        follow = self.client.get("/panel/")
        self.assertEqual(follow.status_code, 200)

    def test_anonymous_root_follows_to_login(self):
        resp = self.client.get("/", follow=True)
        self.assertContains(resp, "Admin panel", status_code=200)

    def test_root_post_not_redirected(self):
        """Only the bare root GET redirects; POST / is a 405, not a redirect."""
        resp = self.client.post("/")
        self.assertEqual(resp.status_code, 405)


class LanguageSwitcherTests(TestCase):
    """The RU | EN toggle is on EVERY page (base.html, outside block nav),
    posts to set_language with ?next=, and the choice persists via cookie."""

    def setUp(self):
        self.admin = make_user("admin@example.com", Role.Roles.ADMIN)
        self.poll = make_poll(self.admin, is_anonymous=True)
        self.session = AnonymousSession.objects.create_session(self.poll)

    def pages(self):
        return [
            reverse("panel-login"),
            reverse("poll-by-token", args=[self.session.token]),
            "/poll/no-such-token/",
        ]

    def test_switcher_present_on_every_page(self):
        """Admin pages, voting landing, results, error page — switcher everywhere."""
        self.client.login(email="admin@example.com", password="passw0rd!")
        closed = make_poll(self.admin, status=PollStatus.CLOSED)
        closed.finalized_at = timezone.now()
        closed.save()
        pages = [
            reverse("panel-dashboard"),
            reverse("panel-users"),
            reverse("panel-poll-new"),
            reverse("panel-poll-edit", args=[self.poll.id]),
            reverse("panel-poll-results", args=[self.poll.id]),
            reverse("page-poll-results", args=[closed.id]),
            reverse("poll-by-token", args=[self.session.token]),
        ]
        for url in pages:
            resp = self.client.get(url, **HTML)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, 'id="lang-switcher"', msg_prefix=url)
            self.assertContains(resp, 'action="/i18n/setlang/"', msg_prefix=url)
            self.assertContains(resp, 'name="next"', msg_prefix=url)
            self.assertContains(resp, 'value="ru"', msg_prefix=url)
            self.assertContains(resp, 'value="en"', msg_prefix=url)
        # the switcher is even on error pages (base.html wraps everything)
        resp = self.client.get("/poll/no-such-token/", **HTML)
        self.assertContains(resp, 'id="lang-switcher"', status_code=404)

    def test_switcher_on_error_and_login_pages_anonymous(self):
        resp = self.client.get(reverse("panel-login"), **HTML)
        self.assertContains(resp, 'id="lang-switcher"')
        resp = self.client.get("/poll/no-such-token/", **HTML)
        self.assertContains(resp, 'id="lang-switcher"', status_code=404)

    def test_switching_to_ru_sets_cookie_and_redirects_back(self):
        resp = self.client.post(
            "/i18n/setlang/",
            {"language": "ru", "next": reverse("panel-login")},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("panel-login"))
        self.assertEqual(self.client.cookies["django_language"].value, "ru")

    def test_switching_to_en_sets_cookie(self):
        self.client.cookies["django_language"] = "ru"
        resp = self.client.post(
            "/i18n/setlang/",
            {"language": "en", "next": reverse("panel-login")},
        )
        self.assertEqual(self.client.cookies["django_language"].value, "en")

    def test_language_persists_across_requests(self):
        self.client.post("/i18n/setlang/", {"language": "ru", "next": "/"})
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertContains(resp, "Проголосовать")
        self.assertContains(resp, "Защищённый бюллетень")
        self.assertContains(resp, "До окончания")
        # a second request, no switch in between: still Russian
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertContains(resp, "Проголосовать")

    def test_ru_translated_string_on_voting_landing(self):
        """After switching to RU, the voting landing page shows Russian."""
        self.client.cookies["django_language"] = "ru"
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertContains(resp, "Проголосовать")
        self.assertNotContains(resp, "Cast vote")
        # html lang attribute follows the active language
        self.assertContains(resp, '<html lang="ru">')
        # switcher marks RU active
        self.assertContains(resp, 'value="ru" class="lang-btn active"')

    def test_en_string_on_voting_landing(self):
        self.client.cookies["django_language"] = "en"
        resp = self.client.get(reverse("poll-by-token", args=[self.session.token]), **HTML)
        self.assertContains(resp, "Cast vote")
        self.assertContains(resp, '<html lang="en">')

    def test_ru_login_page_translated(self):
        self.client.cookies["django_language"] = "ru"
        resp = self.client.get(reverse("panel-login"), **HTML)
        self.assertContains(resp, "Войти")
        self.assertContains(resp, "Панель администратора")

    def test_ru_error_page_translated(self):
        self.client.cookies["django_language"] = "ru"
        resp = self.client.get("/poll/no-such-token/", **HTML)
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Ссылка не найдена", status_code=404)

    def test_json_api_stays_english_regardless_of_language(self):
        """Machine API messages are not localized even with a RU cookie."""
        self.client.cookies["django_language"] = "ru"
        resp = self.client.get("/poll/no-such-token/")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Invalid voting link.", status_code=404)

    def test_default_language_is_english_without_cookie(self):
        resp = self.client.get(reverse("panel-login"), **HTML)
        self.assertContains(resp, "Sign in")
