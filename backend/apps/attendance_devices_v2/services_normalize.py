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

# Normalize chỉ dùng để chống bấm lặp / trùng cross-device trong thời gian rất ngắn.
# KHÔNG dùng window này để đối chiếu ca. Đối chiếu ca dùng AttendanceSettings.window_minutes
# trong services_master_list_compute.py.
DEFAULT_DEDUPE_WINDOW_SECONDS = 120      # 2 phút
MAX_DEDUPE_WINDOW_SECONDS = 180          # chặn cứng 3 phút để tránh gộp sai các mốc hợp lệ
MIN_DEDUPE_WINDOW_SECONDS = 10           # chống cấu hình 0/âm/quá nhỏ gây mất dedupe cơ bản


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
    configured_dedupe_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS
    effective_dedupe_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS
    dedupe_warning: str = ""


def get_dedupe_window_seconds() -> int:
    """
    Window dedupe cho Normalize.

    Ý nghĩa đúng: gộp các lần bấm lặp rất gần nhau, ví dụ bấm 2-3 lần trong vài giây/phút.
    Không được để window này lớn như window đối chiếu ca. Nếu cấu hình cluster_minutes quá lớn,
    hệ thống sẽ cap tối đa 3 phút để tránh gộp sai các lần chấm hợp lệ, ví dụ 16:33 và 16:50.
    """
    s = AttendanceSettings.objects.first()
    configured = DEFAULT_DEDUPE_WINDOW_SECONDS
    if s and getattr(s, "cluster_minutes", None):
        try:
            configured = int(s.cluster_minutes) * 60
        except Exception:
            configured = DEFAULT_DEDUPE_WINDOW_SECONDS

    if configured <= 0:
        return DEFAULT_DEDUPE_WINDOW_SECONDS
    if configured < MIN_DEDUPE_WINDOW_SECONDS:
        return MIN_DEDUPE_WINDOW_SECONDS
    if configured > MAX_DEDUPE_WINDOW_SECONDS:
        return MAX_DEDUPE_WINDOW_SECONDS
    return configured


def _dedupe_window_info() -> tuple[int, int, str]:
    s = AttendanceSettings.objects.first()
    configured = DEFAULT_DEDUPE_WINDOW_SECONDS
    if s and getattr(s, "cluster_minutes", None):
        try:
            configured = int(s.cluster_minutes) * 60
        except Exception:
            configured = DEFAULT_DEDUPE_WINDOW_SECONDS

    effective = get_dedupe_window_seconds()
    warning = ""
    if configured != effective:
        warning = (
            f"cluster_minutes cấu hình tương đương {configured} giây, "
            f"normalize dùng {effective} giây để tránh gộp sai mốc chấm công."
        )
    return configured, effective, warning


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


def _find_existing_normalized(
    *,
    emp: Employee,
    event_time_utc,
    window: timedelta,
) -> AttendanceNormalizedPunchV2 | None:
    """
    Tìm normalized punch đã có trong cửa sổ dedupe.

    Quan trọng: nếu có nhiều mốc trong cửa sổ, chọn mốc gần nhất, không chọn bản ghi đầu tiên
    theo thời gian. Điều này giúp dữ liệu ổn định hơn khi có nhiều thiết bị / nhiều lần retry.
    """
    left = event_time_utc - window
    right = event_time_utc + window
    candidates = list(
        AttendanceNormalizedPunchV2.objects
        .filter(employee=emp, canonical_time_utc__gte=left, canonical_time_utc__lte=right)
        .only("id", "employee", "canonical_time_utc", "best_device", "method", "source_count", "sources_json")
        .order_by("canonical_time_utc")
    )
    if not candidates:
        return None
    return min(candidates, key=lambda p: abs((p.canonical_time_utc - event_time_utc).total_seconds()))


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
    - Dedupe chỉ gộp các lần chấm rất gần nhau, tối đa 3 phút. Không gộp các mốc cách nhau
      xa như 16:33 và 16:50.
    """
    if limit <= 0:
        limit = 1000

    configured_window_seconds, effective_window_seconds, warning = _dedupe_window_info()
    window = timedelta(seconds=effective_window_seconds)

    base_qs = AttendanceRawPunchV2.objects.filter(normalized_at__isnull=True)
    if since_id is not None:
        base_qs = base_qs.filter(id__gt=since_id)

    emp_map = _employee_card_map()
    card_ids = list(emp_map.keys())
    result = NormalizeResult(
        configured_dedupe_seconds=configured_window_seconds,
        effective_dedupe_seconds=effective_window_seconds,
        dedupe_warning=warning,
    )

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

        existing = _find_existing_normalized(emp=emp, event_time_utc=r.event_time_utc, window=window)

        source_item = {
            "raw_id": r.id,
            "device_id": r.device_id,
            "method": r.method,
            "time_utc": r.event_time_utc.isoformat(),
            "time_local": r.event_time_local.isoformat() if r.event_time_local else None,
        }

        if not existing:
            norm = AttendanceNormalizedPunchV2.objects.create(
                employee=emp,
                canonical_time_utc=r.event_time_utc,
                best_device=r.device,
                method=(r.method or "OTHER").upper(),
                source_count=1,
                sources_json=[source_item],
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
            sources.append(source_item)
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
