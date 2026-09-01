import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PollStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ACTIVE = "active", _("Active")
    CLOSED = "closed", _("Closed")


class Poll(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="polls")
    is_anonymous = models.BooleanField(default=False)
    allow_multiple_options = models.BooleanField(default=False)
    results_visibility = models.CharField(
        max_length=10,
        choices=[("public", _("Public")), ("hidden", _("Hidden"))],
        default="public",
        help_text=_("Hidden: only Admin/Secretariat see results; public page returns 403."),
    )
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=PollStatus.choices, default=PollStatus.DRAFT)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} [{self.status}]"

    @property
    def is_open(self):
        now = timezone.now()
        return self.status == PollStatus.ACTIVE and self.start_at <= now <= self.end_at

    @property
    def is_finalized(self):
        return self.finalized_at is not None


class Option(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["poll", "order"], name="uniq_option_order_per_poll")]

    def __str__(self):
        return f"{self.poll.title} #{self.order}: {self.text}"


class Vote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.PROTECT, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="votes")
    options = models.ManyToManyField(Option, related_name="votes")
    voted_at = models.DateTimeField(auto_now_add=True)
    fingerprint_hash = models.CharField(max_length=64, db_index=True, null=True, blank=True)
    is_valid = models.BooleanField(default=True)
    anonymous_session = models.ForeignKey("polls.AnonymousSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="votes")

    class Meta:
        ordering = ["-voted_at"]
        constraints = [
            # One vote per user per poll (identified voting)
            models.UniqueConstraint(fields=["poll", "user"], condition=models.Q(user__isnull=False), name="uniq_vote_per_user_per_poll"),
            # One vote per fingerprint per poll (anonymous voting)
            models.UniqueConstraint(fields=["poll", "fingerprint_hash"], condition=models.Q(fingerprint_hash__isnull=False), name="uniq_vote_per_fingerprint_per_poll"),
            # A one-time link must remain one-time even when two requests race.
            models.UniqueConstraint(fields=["anonymous_session"], condition=models.Q(anonymous_session__isnull=False), name="uniq_vote_per_anonymous_session"),
        ]

    def __str__(self):
        who = self.user.email if self.user else f"anon:{(self.fingerprint_hash or '')[:12]}"
        return f"Vote by {who} in {self.poll.title}"


class AnonymousSessionManager(models.Manager):
    def create_session(self, poll, ttl_hours=None):
        """Create a one-shot link token for a poll (Admin generates links)."""
        from datetime import timedelta

        expires_at = poll.end_at or (timezone.now() + timedelta(hours=24))
        if ttl_hours is not None:
            expires_at = min(expires_at, timezone.now() + timedelta(hours=ttl_hours))
        return self.create(poll=poll, token=secrets.token_urlsafe(32), expires_at=expires_at)


class AnonymousSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="anonymous_sessions")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    fingerprint = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    objects = AnonymousSessionManager()

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"Session for {self.poll.title} (used={self.used})"
