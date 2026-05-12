from datetime import datetime

from django.core.management.base import BaseCommand

from apps.attendance_devices_v2.services_master_list_compute import compute_master_list_for_unit_date


class Command(BaseCommand):
    help = "Commit-only compute: tạo PunchMatchV2 (audit theo mốc) + cập nhật Master List (v2)."

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True, help="Ngày làm việc YYYY-MM-DD")
        parser.add_argument("--unit-id", required=True, type=int, help="OrgUnit ID (đơn vị chốt công)")
        parser.add_argument("--run-id", default="manual", help="Compute run id (để truy vết)")
        parser.add_argument("--compute-version", type=int, default=1, help="Phiên bản compute")

    def handle(self, *args, **options):
        work_date_str = options["date"]
        try:
            work_date = datetime.strptime(work_date_str, "%Y-%m-%d").date()
        except Exception:
            raise SystemExit(f"--date không hợp lệ, cần YYYY-MM-DD. Nhận: {work_date_str}")

        unit_id = int(options["unit_id"])
        run_id = options.get("run_id") or "manual"
        compute_version = int(options.get("compute_version") or 1)

        res = compute_master_list_for_unit_date(
            unit_id=unit_id,
            work_date=work_date,
            source="commit",
            compute_run_id=run_id,
            compute_version=compute_version,
        )

        self.stdout.write(self.style.SUCCESS(
            f"OK compute master v2: date={res.work_date}, unit_id={res.unit_id}, commit_id={res.commit_id}, "
            f"employees_scanned={res.employees_scanned}, matches_created={res.matches_created}, "
            f"master_rows={res.master_rows_upserted}, exempt_rows={res.exempt_rows}. {res.notes}"
        ))