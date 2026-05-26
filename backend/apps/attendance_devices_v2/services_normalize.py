from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
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
    marked_no_uid: int = 0
    pending_unmapped_hint: str = ""


def get_dedupe_window_seconds() -> int:
    s = AttendanceSettings.objects.first()
    if s and s.cluster_minutes:
        return int(s.cluster_minutes) * 60
    return 120


def _employee_card_map() -> dict[str, Employee]:
    """
    Map mã thẻ -> Employee.

    Chỉ lấy các card_id có giá trị. Raw chưa map sẽ KHÔNG bị chọn xử lý ở vòng chính,
    nhờ vậy các UID chưa có trong hồ sơ nhân sự không làm nghẽn hàng đợi normalize.
    """
    qs = Employee.objects.exclude(card_id__isnull=True).exclude(card_id="")
    result: dict[str, Employee] = {}
    for e in qs.only("id", "card_id"):
        card = (e.card_id or "").strip()
        if card and card not in result:
            result[card] = e
    return result


@transaction.atomic
def normalize_raw_punches(
    *,
    limit: int = 1000,
    since_id: int | None = None,
) -> NormalizeResult:
    """
    Normalize idempotent, không bị nghẽn bởi UID chưa map nhân sự.

    Quy tắc:
    - Raw có device_user_id khớp Employee.card_id => normalize thành AttendanceNormalizedPunchV2.
    - Raw không có device_user_id => đánh dấu normalized_at để không quét lại vô ích.
    - Raw có device_user_id nhưng CHƯA khớp Employee.card_id => giữ normalized_at=NULL,
      nhưng không đưa vào batch xử lý chính. Khi sau này cập nhật Employee.card_id, raw đó
      sẽ tự được chọn lại ở lần normalize tiếp theo.

    Lý do sửa:
    - Bản cũ lấy các raw normalized_at=NULL theo id tăng dần. Nếu đầu hàng đợi có nhiều UID
      chưa map, batch sau bị chặn, raw mới phía sau chậm được normalize.
    """
    if limit <= 0:
        limit = 1000

    window_seconds = get_dedupe_window_seconds()
    window = timedelta(seconds=window_seconds)

    base_qs = AttendanceRawPunchV2.objects.filter(normalized_at__isnull=True)
    if since_id is not None:
        base_qs = base_qs.filter(id__gt=since_id)

    emp_map = _employee_card_map()
    card_ids = list(emp_map.keys())
    result = NormalizeResult()

    now = dj_timezone.now()

    # Không có card_id nào trong hồ sơ nhân sự: chỉ xử lý raw không có UID, còn raw có UID giữ lại chờ map.
    if not card_ids:
        no_uid_raws = list(
            base_qs.filter(Q(device_user_id__isnull=True) | Q(device_user_id="")).order_by("id")[:limit]
        )
        result.scanned = len(no_uid_raws)
        for r in no_uid_raws:
            result.unresolved += 1
            result.marked_no_uid += 1
            r.normalized_at = now
            r.save(update_fields=["normalized_at"])
        result.pending_unmapped_hint = "Chưa có Employee.card_id nào để map raw có UID."
        return result

    # Chỉ lấy raw có UID đã map được với Employee.card_id. Các UID chưa map sẽ không chặn queue.
    raws = list(
        base_qs
        .filter(device_user_id__in=card_ids)
        .order_by("id")[:limit]
    )
    result.scanned += len(raws)

    for r in raws:
        uid = (r.device_user_id or "").strip()
        emp = emp_map.get(uid)
        if not emp:
            # Trường hợp hiếm: raw được query ra nhưng sau strip không khớp.
            # Giữ normalized_at=NULL để còn xử lý lại sau, nhưng không chặn các raw khác.
            result.unresolved += 1
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
            update_fields = ["source_count", "sources_json"]
            if new_method != norm.method:
                norm.method = new_method
                norm.best_device = r.device
                update_fields.extend(["method", "best_device"])

            sources = norm.sources_json or []
            sources.append({
                "raw_id": r.id,
                "device_id": r.device_id,
                "method": r.method,
                "time_utc": r.event_time_utc.isoformat(),
            })
            norm.sources_json = sources
            norm.save(update_fields=update_fields)
            result.merged_into_existing += 1

        # Đánh dấu raw đã normalized + liên kết về norm.
        r.normalized_punch = norm
        r.normalized_at = now
        r.save(update_fields=["normalized_punch", "normalized_at"])

    # Nếu batch chưa đủ limit, xử lý thêm raw không có UID để chúng không bị quét lặp vô ích.
    remaining = max(0, limit - len(raws))
    if remaining:
        no_uid_raws = list(
            base_qs.filter(Q(device_user_id__isnull=True) | Q(device_user_id="")).order_by("id")[:remaining]
        )
        result.scanned += len(no_uid_raws)
        for r in no_uid_raws:
            result.unresolved += 1
            result.marked_no_uid += 1
            r.normalized_at = now
            r.save(update_fields=["normalized_at"])

    # Gợi ý vận hành: còn raw có UID nhưng chưa map Employee.card_id.
    # Không count toàn bộ để tránh query nặng; chỉ kiểm tra tồn tại.
    has_unmapped = (
        base_qs
        .exclude(Q(device_user_id__isnull=True) | Q(device_user_id=""))
        .exclude(device_user_id__in=card_ids)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )
    if has_unmapped:
        result.pending_unmapped_hint = "Còn raw có UID chưa map Employee.card_id; chúng được giữ lại và không chặn batch mới."

    return result
