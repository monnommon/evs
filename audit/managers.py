from django.db.models import Manager


class ImmutableAuditManager(Manager):
    """Blocks UPDATE/DELETE on AuditLog via the ORM (defense in depth).

    Writes happen only through audit.utils.log_event (INSERT + the single
    hash-backfill UPDATE issued directly on a plain queryset).
    """

    def get_queryset(self):
        return super().get_queryset()

    def update(self, *args, **kwargs):
        raise PermissionError("AuditLog is append-only: UPDATE is not allowed.")

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditLog is append-only: DELETE is not allowed.")

    def bulk_update(self, *args, **kwargs):
        raise PermissionError("AuditLog is append-only: bulk_update is not allowed.")

    def create(self, **kwargs):
        if "current_hash" in kwargs:
            kwargs.pop("current_hash", None)
        return super().create(**kwargs)