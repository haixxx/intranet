from django.core.management.base import BaseCommand
from apps.attendance_devices.services_resolve import resolve_batch


class Command(BaseCommand):
    help = "Resolve AttendanceRawEvent.employee_id using HR.card_id first, then per-device mapping."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=2000)

    def handle(self, *args, **options):
        limit = options["limit"]
        updated = resolve_batch(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} raw events"))