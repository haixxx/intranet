from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet
from django.utils import timezone as dj_timezone

from apps.attendance_devices_v2.models import (
    AttendanceDeviceBackfillReportV2,
    AttendanceDeviceStatusReportV2,
    AttendanceDeviceTimeSyncReportV2,
    AttendanceIngestLogV2,
    AttendancePunchMatchV2,
)


def _positive_or_disabled(value: int, option_name: str) -> int:
    value = int(value)
    if value < -1:
        raise CommandError(f"{option_name} phải >= 0 hoặc = -1 để bỏ qua.")
    return value


def _positive(value: int, option_name: str) -> int:
    value = int(value)
    if value <= 0:
        raise CommandError(f"{option_name} phải > 0.")
    return value


def _count_or_delete(qs: QuerySet, *, apply: bool, batch_size: int) -> int:
    """
    Đếm trước để dry-run rõ ràng. Khi --apply, xóa theo từng lô nhỏ để tránh
    giữ transaction/lock quá lâu trên hệ thống đang vận hành.
    """
    count = qs.count()
    if not apply or count == 0:
        return count

    while True:
        ids = list(qs.order_by("pk").values_list("pk", flat=True)[:batch_size])
        if not ids:
            break
        qs.model.objects.filter(pk__in=ids).delete()

    return count


def _latest_ids_by_device(model, *, time_field: str) -> set[int]:
    """Giữ lại bản mới nhất của mỗi thiết bị, kể cả khi bản đó đã quá hạn lưu."""
    ids: set[int] = set()
    device_ids = model.objects.values_list("device_id", flat=True).distinct()
    for device_id in device_ids.iterator():
        latest_id = (
            model.objects
            .filter(device_id=device_id)
            .order_by(f"-{time_field}", "-id")
            .values_list("id", flat=True)
            .first()
        )
        if latest_id:
            ids.add(int(latest_id))
    return ids


class Command(BaseCommand):
    help = (
        "Dọn log phụ của attendance_devices_v2 theo từng lô nhỏ. "
        "Không xóa RAW/Normalized/MasterList vì đây là dữ liệu nghiệp vụ cần giữ."
    )

    def add_arguments(self, parser):
        parser.add_argument("--punch-match-days", type=int, default=14, help="Giữ audit PunchMatch trong N ngày. -1 = không dọn.")
        parser.add_argument("--ingest-log-days", type=int, default=30, help="Giữ IngestLog trong N ngày. -1 = không dọn.")
        parser.add_argument("--status-report-days", type=int, default=30, help="Giữ StatusReport trong N ngày. -1 = không dọn.")
        parser.add_argument("--backfill-report-days", type=int, default=60, help="Giữ BackfillReport trong N ngày. -1 = không dọn.")
        parser.add_argument("--time-sync-report-days", type=int, default=180, help="Giữ TimeSyncReport trong N ngày. -1 = không dọn.")
        parser.add_argument("--batch-size", type=int, default=5000, help="Số dòng xóa mỗi lô khi dùng --apply.")
        parser.add_argument("--apply", action="store_true", help="Thực sự xóa. Nếu không truyền thì chỉ dry-run.")

    def handle(self, *args, **options):
        now = dj_timezone.now()
        apply = bool(options.get("apply"))
        batch_size = _positive(options["batch_size"], "--batch-size")

        punch_days = _positive_or_disabled(options["punch_match_days"], "--punch-match-days")
        ingest_days = _positive_or_disabled(options["ingest_log_days"], "--ingest-log-days")
        status_days = _positive_or_disabled(options["status_report_days"], "--status-report-days")
        backfill_days = _positive_or_disabled(options["backfill_report_days"], "--backfill-report-days")
        time_sync_days = _positive_or_disabled(options["time_sync_report_days"], "--time-sync-report-days")

        mode_label = self.style.WARNING("APPLY" if apply else "DRY-RUN")
        self.stdout.write(f"{mode_label}: prune attendance_devices_v2 logs; batch_size={batch_size}")

        results: list[tuple[str, int]] = []

        if punch_days >= 0:
            cutoff = now - timedelta(days=punch_days)
            qs = AttendancePunchMatchV2.objects.filter(created_at__lt=cutoff)
            results.append((
                f"AttendancePunchMatchV2 cũ hơn {punch_days} ngày",
                _count_or_delete(qs, apply=apply, batch_size=batch_size),
            ))

        if ingest_days >= 0:
            cutoff = now - timedelta(days=ingest_days)
            keep_ids = _latest_ids_by_device(AttendanceIngestLogV2, time_field="started_at")
            qs = AttendanceIngestLogV2.objects.filter(created_at__lt=cutoff).exclude(id__in=keep_ids)
            results.append((
                f"AttendanceIngestLogV2 cũ hơn {ingest_days} ngày, giữ log mới nhất mỗi thiết bị",
                _count_or_delete(qs, apply=apply, batch_size=batch_size),
            ))

        if status_days >= 0:
            cutoff = now - timedelta(days=status_days)
            keep_ids = _latest_ids_by_device(AttendanceDeviceStatusReportV2, time_field="reported_at")
            qs = AttendanceDeviceStatusReportV2.objects.filter(reported_at__lt=cutoff).exclude(id__in=keep_ids)
            results.append((
                f"AttendanceDeviceStatusReportV2 cũ hơn {status_days} ngày, giữ report mới nhất mỗi thiết bị",
                _count_or_delete(qs, apply=apply, batch_size=batch_size),
            ))

        if backfill_days >= 0:
            cutoff = now - timedelta(days=backfill_days)
            keep_ids = _latest_ids_by_device(AttendanceDeviceBackfillReportV2, time_field="reported_at")
            qs = AttendanceDeviceBackfillReportV2.objects.filter(reported_at__lt=cutoff).exclude(id__in=keep_ids)
            results.append((
                f"AttendanceDeviceBackfillReportV2 cũ hơn {backfill_days} ngày, giữ report mới nhất mỗi thiết bị",
                _count_or_delete(qs, apply=apply, batch_size=batch_size),
            ))

        if time_sync_days >= 0:
            cutoff = now - timedelta(days=time_sync_days)
            keep_ids = _latest_ids_by_device(AttendanceDeviceTimeSyncReportV2, time_field="reported_at")
            qs = AttendanceDeviceTimeSyncReportV2.objects.filter(reported_at__lt=cutoff).exclude(id__in=keep_ids)
            results.append((
                f"AttendanceDeviceTimeSyncReportV2 cũ hơn {time_sync_days} ngày, giữ report mới nhất mỗi thiết bị",
                _count_or_delete(qs, apply=apply, batch_size=batch_size),
            ))

        total = 0
        for label, count in results:
            total += count
            self.stdout.write(f"- {label}: {count} dòng")

        self.stdout.write(f"Tổng số dòng phù hợp điều kiện: {total}")

        if apply:
            self.stdout.write(self.style.SUCCESS("Đã dọn log theo phạm vi trên."))
        else:
            self.stdout.write(self.style.WARNING("Đây là dry-run. Thêm --apply để xóa thật."))
