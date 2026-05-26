from __future__ import annotations

from datetime import datetime, date as date_cls, timedelta
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from apps.attendance.models_batch import AttendanceCommit
from apps.attendance_devices_v2.services_master_list_compute import compute_master_list_for_unit_date


def _parse_date(raw: str | None, *, option_name: str) -> date_cls | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception as exc:
        raise CommandError(f"{option_name} không hợp lệ, cần YYYY-MM-DD. Nhận: {raw}") from exc


class Command(BaseCommand):
    help = (
        "Tính lại MasterList v2 theo các AttendanceCommit đã có. "
        "Mặc định tính ngày hôm nay; có thể dùng --date, --from-date/--to-date hoặc --days-back."
    )

    def add_arguments(self, parser):
        parser.add_argument("--date", default="", help="Tính một ngày YYYY-MM-DD. Nếu bỏ trống sẽ dùng hôm nay.")
        parser.add_argument("--from-date", default="", help="Từ ngày YYYY-MM-DD, dùng cho khoảng ngày.")
        parser.add_argument("--to-date", default="", help="Đến ngày YYYY-MM-DD, dùng cho khoảng ngày.")
        parser.add_argument(
            "--days-back",
            type=int,
            default=0,
            help="Nếu không truyền --date/--from-date, tính từ hôm nay - days-back đến hôm nay. Ví dụ --days-back 1 = hôm qua + hôm nay.",
        )
        parser.add_argument("--unit-id", type=int, default=None, help="Chỉ tính một OrgUnit ID cụ thể.")
        parser.add_argument("--run-prefix", default="cron", help="Prefix cho compute_run_id.")
        parser.add_argument("--compute-version", type=int, default=1, help="Phiên bản compute.")
        parser.add_argument("--dry-run", action="store_true", help="Chỉ liệt kê unit/date sẽ tính, không ghi DB.")
        parser.add_argument("--fail-fast", action="store_true", help="Dừng ngay nếu một unit/date bị lỗi.")

    def handle(self, *args, **options):
        today = dj_timezone.localdate()

        date_single = _parse_date(options.get("date"), option_name="--date")
        from_date = _parse_date(options.get("from_date"), option_name="--from-date")
        to_date = _parse_date(options.get("to_date"), option_name="--to-date")

        if from_date or to_date:
            from_date = from_date or to_date or today
            to_date = to_date or from_date
        elif date_single:
            from_date = to_date = date_single
        else:
            days_back = int(options.get("days_back") or 0)
            if days_back < 0:
                raise CommandError("--days-back không được âm.")
            from_date = today - timedelta(days=days_back)
            to_date = today

        if from_date > to_date:
            from_date, to_date = to_date, from_date

        unit_id = options.get("unit_id")
        run_prefix = (options.get("run_prefix") or "cron").strip() or "cron"
        compute_version = int(options.get("compute_version") or 1)
        dry_run = bool(options.get("dry_run"))
        fail_fast = bool(options.get("fail_fast"))

        commits_qs = AttendanceCommit.objects.filter(work_date__gte=from_date, work_date__lte=to_date)
        if unit_id:
            commits_qs = commits_qs.filter(unit_id=unit_id)

        pairs = list(
            commits_qs
            .values_list("unit_id", "work_date", "id")
            .order_by("work_date", "unit_id")
        )

        if not pairs:
            scope = f"{from_date:%Y-%m-%d} -> {to_date:%Y-%m-%d}"
            if unit_id:
                scope += f", unit_id={unit_id}"
            self.stdout.write(self.style.WARNING(f"Không có AttendanceCommit trong phạm vi: {scope}. Không compute."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN: sẽ compute {len(pairs)} unit/date trong phạm vi {from_date:%Y-%m-%d} -> {to_date:%Y-%m-%d}."
            ))
            for uid, wd, commit_id in pairs:
                self.stdout.write(f"- date={wd:%Y-%m-%d}, unit_id={uid}, commit_id={commit_id}")
            return

        ok = 0
        failed = 0
        total_rows = 0
        total_matches = 0
        errors: list[str] = []

        for uid, wd, commit_id in pairs:
            run_id = f"{run_prefix}-{wd:%Y%m%d}-u{uid}-{uuid4().hex[:8]}"
            try:
                res = compute_master_list_for_unit_date(
                    unit_id=uid,
                    work_date=wd,
                    source="commit",
                    compute_run_id=run_id,
                    compute_version=compute_version,
                )
                ok += 1
                total_rows += int(res.master_rows_upserted or 0)
                total_matches += int(res.matches_created or 0)
                self.stdout.write(
                    f"OK date={res.work_date}, unit_id={res.unit_id}, commit_id={res.commit_id}, "
                    f"master_rows={res.master_rows_upserted}, matches={res.matches_created}. {res.notes}"
                )
            except Exception as exc:
                failed += 1
                msg = f"ERROR date={wd:%Y-%m-%d}, unit_id={uid}, commit_id={commit_id}: {exc}"
                errors.append(msg)
                self.stderr.write(self.style.ERROR(msg))
                if fail_fast:
                    raise CommandError(msg) from exc

        summary = (
            f"DONE compute MasterList v2: commits={len(pairs)}, ok={ok}, failed={failed}, "
            f"master_rows={total_rows}, matches={total_matches}, range={from_date:%Y-%m-%d}->{to_date:%Y-%m-%d}"
        )
        if failed:
            self.stdout.write(self.style.WARNING(summary))
            self.stdout.write(self.style.WARNING("Một số lỗi đầu tiên: " + " | ".join(errors[:5])))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
