from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, date, timezone as py_timezone  # NOTE: dùng Python's timezone.utc
import hashlib

from apps.hr.models import Employee
from apps.attendance_devices.models import AttendanceDevice, AttendanceRawEvent


class Command(BaseCommand):
    help = "Seed sample AttendanceRawEvent for a given employee_code, device_id, and date. Example times: 07:55,12:01,13:02,17:35"

    def add_arguments(self, parser):
        parser.add_argument("--employee_code", type=str, required=True)
        parser.add_argument("--device_id", type=int, required=True)
        parser.add_argument("--date", type=str, required=True, help="YYYY-MM-DD (local date)")
        parser.add_argument("--times", type=str, default="08:00,17:00", help="Comma times HH:MM,HH:MM,... in local time")
        parser.add_argument("--method", type=str, default="OTHER", choices=["FP", "CARD", "FACE", "OTHER"])
        parser.add_argument("--direction", type=str, default="UNKNOWN", choices=["UNKNOWN", "IN", "OUT"])

    def handle(self, *args, **options):
        employee_code = options["employee_code"].strip()
        device_id = options["device_id"]
        date_str = options["date"]
        times_str = options["times"]
        method = options["method"]
        direction = options["direction"]

        emp = Employee.objects.filter(employee_code=employee_code).first()
        if not emp:
            raise CommandError(f"Employee with code '{employee_code}' not found")

        device = AttendanceDevice.objects.filter(pk=device_id).first()
        if not device:
            raise CommandError(f"AttendanceDevice id={device_id} not found")

        try:
            y, m, d = [int(x) for x in date_str.split("-")]
            work_date = date(y, m, d)
        except Exception:
            raise CommandError("Invalid --date format. Use YYYY-MM-DD")

        times = []
        for t in [x.strip() for x in times_str.split(",") if x.strip()]:
            try:
                hh, mm = [int(x) for x in t.split(":")]
                # tạo datetime local aware theo TIME_ZONE của Django
                naive_dt = datetime(y, m, d, hh, mm, 0)
                local_dt = timezone.make_aware(naive_dt, timezone.get_current_timezone())
                times.append(local_dt)
            except Exception:
                raise CommandError(f"Invalid time '{t}'. Use HH:MM")

        created = 0
        for local_dt in times:
            utc_dt = local_dt.astimezone(py_timezone.utc)  # FIX: dùng Python's UTC
            device_user_id = emp.card_id or emp.employee_code  # ưu tiên card_id nếu có

            # Tạo dedup_hash: device_id + device_user_id + utc timestamp
            key = f"{device.id}:{device_user_id}:{utc_dt.isoformat()}"
            dedup_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:64]

            AttendanceRawEvent.objects.create(
                device=device,
                device_user_id=str(device_user_id),
                employee=emp,  # set sẵn employee để compute chạy ngay; nếu muốn test resolve thì set None
                event_time_local=local_dt,
                event_time_utc=utc_dt,
                method=method,
                direction=direction,
                device_event_id=None,
                dedup_hash=dedup_hash,
                meta_json={"seed": True},
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} raw events for {employee_code} on {work_date} (device {device_id})"
        ))