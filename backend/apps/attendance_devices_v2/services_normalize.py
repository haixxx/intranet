from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.attendance.models import AttendanceSettings
from apps.hr.models import Employee

from .models import AttendanceRawPunchV2, AttendanceNormalizedPunchV2


METHOD_PRIORITY = {
    "FACE": 3,
    "FP": 2,
    "CARD": 1,
    "OTHER": 0,
}


def _best_method(a: str, b: str) -> str:
    pa = METHOD_PRIORITY.get((a or "OTHER").upper(), 0)
    pb = METHOD_PRIORITY.get((b or "OTHER").upper(), 0)
    return a if pa >= pb else b


@dataclass
class NormalizeResult:
    scanned: int = 0
    resolved: int = 0
    unresolved: int = 0
    created_norm: int = 0
    merged_into_existing: int = 0


def get_dedupe_window_seconds() -> int:
    s = AttendanceSettings.objects.first()
    if s and s.cluster_minutes:
        return int(s.cluster_minutes) * 60
    return 120


@transaction.atomic
def normalize_raw_punches(
    *,
    limit: int = 1000,
    since_id: int | None = None,
) -> NormalizeResult:
    """
    Normalize idempotent:
    - chỉ xử lý raw chưa normalized (normalized_at is null)
    - sau khi xử lý sẽ set normalized_punch + normalized_at
    """
    window_seconds = get_dedupe_window_seconds()
    window = timedelta(seconds=window_seconds)

    qs = AttendanceRawPunchV2.objects.filter(normalized_at__isnull=True).order_by("id")
    if since_id is not None:
        qs = qs.filter(id__gt=since_id)

    raws = list(qs[:limit])
    result = NormalizeResult(scanned=len(raws))

    if not raws:
        return result

    uids = {r.device_user_id for r in raws if r.device_user_id}
    emp_map = {e.card_id: e for e in Employee.objects.filter(card_id__in=list(uids))}

    now = dj_timezone.now()

    for r in raws:
        uid = (r.device_user_id or "").strip()
        if not uid:
            result.unresolved += 1
            r.normalized_at = now
            r.save(update_fields=["normalized_at"])
            continue

        emp = emp_map.get(uid)
        if not emp:
            # chưa map được Employee.card_id
            result.unresolved += 1
            # vẫn đánh dấu normalized_at để lần sau không quét lại? -> KHÔNG.
            # Vì sau này nhân sự có thể cập nhật card_id, ta muốn chạy lại.
            # => không set normalized_at.
            continue

        result.resolved += 1

        t = r.event_time_utc
        left = t - window
        right = t + window

        existing = (
            AttendanceNormalizedPunchV2.objects
            .filter(employee=emp, canonical_time_utc__gte=left, canonical_time_utc__lte=right)
            .order_by("canonical_time_utc")
            .first()
        )

        if not existing:
            norm = AttendanceNormalizedPunchV2.objects.create(
                employee=emp,
                canonical_time_utc=t,
                best_device=r.device,
                method=(r.method or "OTHER").upper(),
                source_count=1,
                sources_json=[{
                    "raw_id": r.id,
                    "device_id": r.device_id,
                    "method": r.method,
                    "time_utc": r.event_time_utc.isoformat(),
                }],
                created_at=now,
            )
            result.created_norm += 1
        else:
            norm = existing
            norm.source_count = (norm.source_count or 1) + 1
            new_method = _best_method(norm.method, (r.method or "OTHER").upper())
            if new_method != norm.method:
                norm.method = new_method
                norm.best_device = r.device
            sources = norm.sources_json or []
            sources.append({
                "raw_id": r.id,
                "device_id": r.device_id,
                "method": r.method,
                "time_utc": r.event_time_utc.isoformat(),
            })
            norm.sources_json = sources
            norm.save(update_fields=["source_count", "method", "best_device", "sources_json"])
            result.merged_into_existing += 1

        # Đánh dấu raw đã normalized + liên kết về norm
        r.normalized_punch = norm
        r.normalized_at = now
        r.save(update_fields=["normalized_punch", "normalized_at"])

    return result