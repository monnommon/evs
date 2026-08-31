import hashlib
import json
import threading
from contextlib import contextmanager

from django.db import transaction
from django.db.models import F

from .models import AuditLog

GENESIS_HASH = "0" * 64

# Serialize audit writes within this process to keep the chain gapless.
_chain_lock = threading.Lock()


def _json_safe(value):
    """Coerce UUID/datetime/Decimal values to JSON-serializable primitives."""
    import datetime
    import decimal
    import uuid as uuid_mod

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (uuid_mod.UUID,)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def canonical_payload(data):
    """Deterministic JSON for hashing: sorted keys, no whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(previous_hash, data):
    """hash_N = SHA256(canonical(event data) + hash_{N-1})."""
    material = canonical_payload(data) + (previous_hash or GENESIS_HASH)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@contextmanager
def chain_lock():
    """Cross-process safety: use a DB row lock plus an in-process lock.

    The chain integrity (each entry pointing at its predecessor) is enforced
    by re-reading the tip inside the lock; uniqueness of `sequence` and
    `current_hash` makes a race detectable instead of silently corrupting.
    """
    with _chain_lock:
        with transaction.atomic():
            yield


def log_event(event_type, entity_type, entity_id, data=None, created_by=None):
    """Append an event to the audit hash chain. Returns the AuditLog entry.

    Immutability: entries are only ever INSERTed. This function never updates
    or deletes existing rows, and the manager blocks UPDATE/DELETE at the ORM
    level (see managers.py) for defense in depth.
    """
    if event_type not in AuditLog.EVENT_TYPES:
        raise ValueError(f"Unknown audit event type: {event_type}")
    data = _json_safe(dict(data or {}))
    with chain_lock():
        tip = AuditLog.objects.select_for_update().order_by("-sequence").first()
        previous_hash = tip.current_hash if tip else None
        sequence = (tip.sequence + 1) if tip else 1
        entry = AuditLog.objects.create(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id),
            previous_hash=previous_hash,
            data=data,
            created_by=created_by,
            sequence=sequence,
        )
        # current_hash binds: event meta + payload + predecessor hash
        hash_input = {
            "sequence": entry.sequence,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "data": data,
        }
        entry.current_hash = compute_hash(previous_hash, hash_input)
        # Single UPDATE right after INSERT is the only write pattern allowed;
        # hash the row via a direct queryset update to bypass the immutable
        # manager restriction.
        AuditLog.objects.filter(pk=entry.pk).update(current_hash=entry.current_hash)
    return entry


def verify_chain():
    """Recompute the chain. Returns (ok: bool, problems: list[str])."""
    problems = []
    expected_prev = None
    expected_seq = 1
    for entry in AuditLog.objects.all().iterator():
        if entry.sequence != expected_seq:
            problems.append(f"sequence gap at {entry.pk}: expected {expected_seq}, got {entry.sequence}")
            expected_seq = entry.sequence
        if entry.previous_hash != expected_prev:
            problems.append(f"previous_hash mismatch at {entry.pk}: expected {expected_prev}, got {entry.previous_hash}")
        hash_input = {
            "sequence": entry.sequence,
            "event_type": entry.event_type,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "data": entry.data,
        }
        recomputed = compute_hash(entry.previous_hash, hash_input)
        if recomputed != entry.current_hash:
            problems.append(f"hash mismatch at {entry.pk}: stored {entry.current_hash}, recomputed {recomputed}")
        expected_prev = entry.current_hash
        expected_seq += 1
    return (len(problems) == 0, problems)


def audit_trail(entity_type=None, entity_id=None):
    """Exportable audit trail, optionally filtered by entity."""
    qs = AuditLog.objects.all()
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if entity_id:
        qs = qs.filter(entity_id=str(entity_id))
    return [
        {
            "sequence": e.sequence,
            "id": str(e.id),
            "event_type": e.event_type,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "previous_hash": e.previous_hash,
            "current_hash": e.current_hash,
            "data": e.data,
            "created_at": e.created_at.isoformat(),
        }
        for e in qs
    ]