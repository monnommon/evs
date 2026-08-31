import uuid

from django.conf import settings
from django.db import models

from .managers import ImmutableAuditManager


class AuditLog(models.Model):
    """Append-only audit entry; entries form a SHA-256 hash chain.

    hash_N = SHA256(canonical(event data) + hash_{N-1})
    Tampering with any entry breaks every subsequent hash.
    """

    EVENT_TYPES = (
        "user_registered",
        "user_logout",
        "password_reset_requested",
        "poll_created",
        "poll_updated",
        "poll_status_changed",
        "vote_cast",
        "anonymous_vote_cast",
        "result_finalized",
        "role_changed",
        "session_generated",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=64)
    previous_hash = models.CharField(max_length=64, null=True, blank=True)
    current_hash = models.CharField(max_length=64, unique=True)
    data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_entries")
    created_at = models.DateTimeField(auto_now_add=True)
    sequence = models.BigIntegerField(editable=False, unique=True)

    objects = ImmutableAuditManager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("AuditLog is append-only: modifying existing entries is not allowed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditLog is append-only: DELETE is not allowed.")

    class Meta:
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.sequence}: {self.event_type}({self.entity_type}/{self.entity_id})"