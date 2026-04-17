from django.core.management.base import BaseCommand

from apps.attendance_devices_v2.services_compute import compute_audit_for_date


class Command(BaseCommand):
    help = "Đối chiếu punches chuẩn hoá (v2) với AttendanceRegistration để tạo audit AttendancePunchMatchV2 (audit-only)."

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True, help="Ngày làm việc YYYY-MM-DD")
        parser.add_argument("--employee-id", type=int, default=None, help="Chỉ chạy cho 1 nhân viên (id)")
        parser.add_argument("--run-id", default="manual", help="Compute run id (để truy vết)")
        # Không dùng --version vì Django đã dùng option này
        parser.add_argument("--compute-version", type=int, default=1, help="Phiên bản compute")

    def handle(self, *args, **options):
        work_date = options["date"]
        employee_id = options.get("employee_id")
        run_id = options.get("run_id") or "manual"
        compute_version = int(options.get("compute_version") or 1)

        employee_ids = [employee_id] if employee_id else None

        res = compute_audit_for_date(
            work_date=work_date,
            employee_ids=employee_ids,
            compute_run_id=run_id,
            compute_version=compute_version,
        )

        self.stdout.write(self.style.SUCCESS(
            f"OK compute audit v2: date={res.work_date}, employees_scanned={res.employees_scanned}, "
            f"matches_created={res.matches_created}. {res.notes}"
        ))