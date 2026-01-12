from datetime import date, timedelta
from django.core.management.base import BaseCommand, CommandError
from apps.attendance_devices.services_dayfacts import compute_day_facts_for_date


class Command(BaseCommand):
    help = "Compute AttendanceDayFacts from raw events. Use --date YYYY-MM-DD or --from YYYY-MM-DD --to YYYY-MM-DD"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD")
        parser.add_argument("--from", dest="from_date", type=str, help="YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", type=str, help="YYYY-MM-DD")

    def handle(self, *args, **options):
        one = options.get("date")
        f = options.get("from_date")
        t = options.get("to_date")

        if one:
            y, m, d = [int(x) for x in one.split("-")]
            wd = date(y, m, d)
            n = compute_day_facts_for_date(wd)
            self.stdout.write(self.style.SUCCESS(f"Computed facts for {wd}: {n} employees"))
            return

        if f and t:
            y1, m1, d1 = [int(x) for x in f.split("-")]
            y2, m2, d2 = [int(x) for x in t.split("-")]
            s = date(y1, m1, d1)
            e = date(y2, m2, d2)
            cur = s
            total = 0
            while cur <= e:
                total += compute_day_facts_for_date(cur)
                cur += timedelta(days=1)
            self.stdout.write(self.style.SUCCESS(f"Computed facts for range {s}..{e}: {total} employees total"))
            return

        raise CommandError("Provide --date or --from and --to")