"""Open/close polls whose schedule says so: draft→active at start_at,
active→closed at end_at. Run from cron/systemd, e.g. every 5 minutes:

    python manage.py poll_lifecycle
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from audit.utils import log_event
from polls.models import Poll, PollStatus


class Command(BaseCommand):
    help = "Activate scheduled drafts and close expired polls."

    def handle(self, *args, **options):
        now = timezone.now()
        opened = 0
        closed = 0
        for poll in Poll.objects.filter(status=PollStatus.DRAFT, start_at__lte=now, end_at__gt=now):
            poll.status = PollStatus.ACTIVE
            poll.save(update_fields=["status"])
            log_event("poll_status_changed", "Poll", str(poll.id), {"from": PollStatus.DRAFT, "to": PollStatus.ACTIVE, "by": "scheduler"}, created_by=None)
            opened += 1
        for poll in Poll.objects.filter(status=PollStatus.ACTIVE, end_at__lte=now):
            poll.status = PollStatus.CLOSED
            poll.save(update_fields=["status"])
            log_event("poll_status_changed", "Poll", str(poll.id), {"from": PollStatus.ACTIVE, "to": PollStatus.CLOSED, "by": "scheduler"}, created_by=None)
            closed += 1
        self.stdout.write(f"opened={opened} closed={closed}")