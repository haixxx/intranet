from datetime import date, timedelta
from django.core.management.base import BaseCommand, CommandError
from apps.attendance_devices.services_overlay import overlay_day, overlay_day_range


class Command(BaseCommand):
    help = "Overlay effective DayFacts (IMPORT/MANUAL over RAW). Use --date YYYY-MM-DD or --from YYYY-MM-DD --to YYYY-MM-DD"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD")
        parser.add_argument("--from", dest="from_date", type=str, help="YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", type=str, help="YYYY-MM-DD")
        parser.add_argument("--employee", dest="employee_id", type=int, help="Optional single employee")

    def handle(self, *args, **options):
        one = options.get("date")
        f = options.get("from_date")
        t = options.get("to_date")
        emp = options.get("employee_id")

        if one:
            y, m, d = [int(x) for x in one.split("-")]
            wd = date(y, m, d)
            if emp:
                overlay_day(emp, wd)
                self.stdout.write(self.style.SUCCESS(f"Overlay {wd} for employee {emp}: done"))
            else:
                # overlay toàn bộ facts có ngày đó
                overlay_day_range(wd, wd)
                self.stdout.write(self.style.SUCCESS(f"Overlay {wd}: done"))
            return

        if f and t:
            y1, m1, d1 = [int(x) for x in f.split("-")]
            y2, m2, d2 = [int(x) for x in t.split("-")]
            s = date(y1, m1, d1)
            e = date(y2, m2, d2)
            total = overlay_day_range(s, e)
            self.stdout.write(self.style.SUCCESS(f"Overlay range {s}..{e}: {total} days updated"))
            return

        raise CommandError("Provide --date or --from and --to")