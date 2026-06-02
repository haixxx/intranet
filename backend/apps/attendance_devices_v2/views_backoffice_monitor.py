from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time, timezone as datetime_timezone
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, OuterRef, Q, Subquery
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _

from apps.organization.models import OrgUnit
from apps.hr.models import Employee
from apps.attendance.models_batch import AttendanceCommit

from .services_normalize import normalize_raw_punches
from .services_master_list_compute import compute_master_list_for_unit_date

from .models import (
    AttendanceDeviceAgentV2,
    AttendanceDeviceV2,
    AttendanceIngestLogV2,
    AttendanceNormalizedPunchV2,
    AttendanceRawPunchV2,
    AttendanceDeviceStatusReportV2,
    AttendanceDeviceBackfillReportV2,
)


ONLINE_MINUTES = 10
STALE_MINUTES = 60
AGENT_ONLINE_MINUTES = 5


@dataclass
class DeviceMonitorRow:
    device: AttendanceDeviceV2
    dynamic_status: str
    dynamic_status_label: str
    dynamic_status_class: str
    last_pull_ago: str
    agent_status: str
    agent_status_label: str
    agent_last_seen_ago: str
    raw_today: int
    raw_24h: int
    raw_pending: int
    unresolved_today: int
    unresolved_raw_today: int
    unresolved_samples: list[dict]
    normalized_today: int
    last_log: AttendanceIngestLogV2 | None
    last_log_status_label: str
    last_log_class: str
    latest_status: AttendanceDeviceStatusReportV2 | None
    latest_backfill: AttendanceDeviceBackfillReportV2 | None
    realtime_label: str
    realtime_class: str
    backfill_label: str
    backfill_class: str
    drift_text: str
    last_error_text: str
    cursor_text: str


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_int(raw: str, default: int) -> int:
    try:
        v = int(raw)
        return v if v > 0 else default
    except Exception:
        return default


def _ago(dt) -> str:
    if not dt:
        return "-"
    now = dj_timezone.now()
    delta = now - dt
    total_sec = int(delta.total_seconds())
    if total_sec < 0:
        total_sec = 0
    if total_sec < 60:
        return f"{total_sec} giây trước"
    minutes = total_sec // 60
    if minutes < 60:
        return f"{minutes} phút trước"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} giờ trước"
    days = hours // 24
    return f"{days} ngày trước"


def _device_status(device: AttendanceDeviceV2, now) -> tuple[str, str, str]:
    if not device.is_active:
        return "DISABLED", "Ngừng dùng", "secondary"
    if not device.last_pull_at:
        return "UNKNOWN", "Chưa có dữ liệu", "dark"
    age_min = (now - device.last_pull_at).total_seconds() / 60
    if age_min <= ONLINE_MINUTES:
        return "ONLINE", "Online", "success"
    if age_min <= STALE_MINUTES:
        return "STALE", "Chậm dữ liệu", "warning"
    return "OFFLINE", "Offline", "danger"


def _agent_status(agent: AttendanceDeviceAgentV2 | None, now) -> tuple[str, str]:
    if not agent:
        return "NO_AGENT", "Chưa gán"
    if agent.status != AttendanceDeviceAgentV2.Status.ACTIVE:
        return "DISABLED", "Không active"
    if not agent.last_seen_at:
        return "UNKNOWN", "Chưa heartbeat"
    age_min = (now - agent.last_seen_at).total_seconds() / 60
    if age_min <= AGENT_ONLINE_MINUTES:
        return "ONLINE", "Agent online"
    return "OFFLINE", "Agent offline"


def _report_age_minutes(report: AttendanceDeviceStatusReportV2 | None, now) -> float | None:
    """Tuổi của report realtime mới nhất, tính theo mốc đáng tin nhất Agent gửi lên."""
    if not report:
        return None
    ref_dt = report.last_device_seen_at or report.last_realtime_at or report.reported_at
    if not ref_dt:
        return None
    return max(0.0, (now - ref_dt).total_seconds() / 60)


def _device_status_from_report(device: AttendanceDeviceV2, report: AttendanceDeviceStatusReportV2 | None, now) -> tuple[str, str, str]:
    """
    Tính trạng thái thiết bị cho dashboard.

    Quy tắc mới:
    - Nếu report realtime còn mới: ưu tiên status do Agent báo.
    - Nếu report realtime đã quá hạn nhưng device.last_pull_at/ingest còn mới: fallback theo last_pull_at.
      Điều này xử lý trường hợp Agent vẫn gửi raw/ingest nhưng chưa gửi device-status mới.
    - Nếu report cũ và last_pull_at cũng cũ: offline.
    """
    if not device.is_active:
        return "DISABLED", "Ngừng dùng", "secondary"

    age_min = _report_age_minutes(report, now)
    if report and age_min is not None and age_min <= STALE_MINUTES:
        if age_min > ONLINE_MINUTES:
            return "STALE", "Chậm realtime", "warning"

        status = report.realtime_status
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.ONLINE:
            return "ONLINE", "Online", "success"
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.RECONNECTING:
            return "STALE", "Đang kết nối lại", "warning"
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.PAUSED_BACKFILL:
            return "ONLINE", "Tạm dừng backfill", "warning"
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.PAUSED_TIME_SYNC:
            return "ONLINE", "Tạm dừng sync giờ", "warning"
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.REALTIME_UNAVAILABLE:
            return "OFFLINE", "Không realtime", "danger"
        if status == AttendanceDeviceStatusReportV2.RealtimeStatus.ERROR:
            return "OFFLINE", "Lỗi realtime", "danger"

    # Report không có hoặc đã quá hạn: fallback theo last_pull_at do ingest raw cập nhật.
    return _device_status(device, now)


def _realtime_badge(report: AttendanceDeviceStatusReportV2 | None, now=None) -> tuple[str, str]:
    if not report:
        return "Chưa báo", "secondary"

    # Không hiển thị ONLINE mãi mãi từ report cũ. Nếu Agent/service đã tắt lâu, badge phải báo quá hạn.
    if now is None:
        now = dj_timezone.now()
    age_min = _report_age_minutes(report, now)
    if age_min is None:
        return "Chưa báo", "secondary"
    if age_min > STALE_MINUTES:
        return "Quá hạn", "danger"
    if age_min > ONLINE_MINUTES:
        return "Chậm báo", "warning"

    status = report.realtime_status
    labels = {
        "ONLINE": "Online",
        "OFFLINE": "Offline",
        "RECONNECTING": "Reconnect",
        "PAUSED_BACKFILL": "Pause backfill",
        "PAUSED_TIME_SYNC": "Pause sync giờ",
        "REALTIME_UNAVAILABLE": "Không realtime",
        "ERROR": "Lỗi",
    }
    css = {
        "ONLINE": "success",
        "OFFLINE": "danger",
        "RECONNECTING": "warning",
        "PAUSED_BACKFILL": "warning",
        "PAUSED_TIME_SYNC": "warning",
        "REALTIME_UNAVAILABLE": "danger",
        "ERROR": "danger",
    }
    return labels.get(status, status), css.get(status, "secondary")


def _backfill_badge(report: AttendanceDeviceBackfillReportV2 | None) -> tuple[str, str]:
    if not report:
        return "Chưa chạy", "secondary"
    status = report.status
    labels = {
        "SUCCESS": "OK",
        "PARTIAL_PENDING": "Pending",
        "FAILED": "Lỗi",
        "SKIPPED": "Bỏ qua",
    }
    css = {
        "SUCCESS": "success",
        "PARTIAL_PENDING": "warning",
        "FAILED": "danger",
        "SKIPPED": "secondary",
    }
    return labels.get(status, status), css.get(status, "secondary")


def _drift_text(report: AttendanceDeviceStatusReportV2 | None) -> str:
    if not report or report.drift_seconds is None:
        return "-"
    sec = int(report.drift_seconds)
    sign = "+" if sec > 0 else ""
    return f"{sign}{sec}s"


def _dict_counts(qs, key_name: str) -> dict[int, int]:
    return {int(x[key_name]): int(x["cnt"]) for x in qs if x[key_name] is not None}


def _short_uid_list(items: list[dict], limit: int = 5) -> list[dict]:
    """Giữ tối đa vài UID để hiển thị gọn trên bảng."""
    return items[:limit]


def _known_card_ids_qs():
    """Subquery card_id hợp lệ trong hồ sơ nhân sự."""
    return (
        Employee.objects
        .exclude(card_id__isnull=True)
        .exclude(card_id="")
        .values("card_id")
    )


def _unmapped_raw_qs():
    """
    Raw chưa normalize vì UID/mã thẻ trên máy chưa khớp Employee.card_id.

    Điều kiện này cố tình CHỈ lấy raw chưa normalize, có UID, nhưng UID không tồn tại
    trong hồ sơ nhân sự. Raw này không tham gia compute và không chặn queue normalize.
    """
    return (
        AttendanceRawPunchV2.objects
        .filter(normalized_at__isnull=True)
        .exclude(Q(device_user_id__isnull=True) | Q(device_user_id=""))
        .exclude(device_user_id__in=Subquery(_known_card_ids_qs()))
    )


def _filtered_device_ids(*, q: str = "", agent_raw: str = "", unit_raw: str = "", active_raw: str = "") -> list[int]:
    qs = AttendanceDeviceV2.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(host__icontains=q) |
            Q(model__icontains=q) |
            Q(serial_no__icontains=q) |
            Q(org_unit__symbol__icontains=q) |
            Q(org_unit__name__icontains=q)
        )
    if agent_raw.isdigit():
        qs = qs.filter(assigned_agent_id=int(agent_raw))
    if unit_raw.isdigit():
        qs = qs.filter(org_unit_id=int(unit_raw))
    if active_raw in {"0", "1"}:
        qs = qs.filter(is_active=(active_raw == "1"))
    return list(qs.values_list("id", flat=True))


@login_required
@permission_required("attendance_devices_v2.view_attendancedevicev2", raise_exception=True)
def normalize_lai_view(request):
    """
    Chạy normalize RawPunch từ giao diện Giám sát thiết bị.

    Lưu ý:
    - Chỉ xử lý raw có UID đã khớp Employee.card_id hoặc raw không có UID.
    - Raw có UID chưa map không chặn hàng đợi; sau khi cập nhật card_id có thể bấm lại nút này.
    """
    if request.method != "POST":
        return redirect("attendance_devices_v2:giam_sat_thiet_bi")

    try:
        limit = int(request.POST.get("limit") or 5000)
    except Exception:
        limit = 5000
    if limit < 100:
        limit = 100
    if limit > 20000:
        limit = 20000

    try:
        result = normalize_raw_punches(limit=limit)
        msg = (
            f"Đã chạy normalize: quét {result.scanned} raw, "
            f"map được {result.resolved}, chưa map {result.unresolved}, "
            f"tạo mới {result.created_norm}, gộp vào mốc cũ {result.merged_into_existing}."
        )
        pending_hint = getattr(result, "pending_unmapped_hint", 0)
        if pending_hint:
            msg += f" Còn khoảng {pending_hint} raw có UID chưa map, không chặn hàng đợi."
        messages.success(request, msg)
    except Exception as exc:
        messages.error(request, f"Chạy normalize bị lỗi: {exc}")

    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("attendance_devices_v2:giam_sat_thiet_bi")


@login_required
@permission_required("attendance_devices_v2.view_attendancedevicev2", raise_exception=True)
def tinh_lai_masterlist_view(request):
    """
    Chạy compute MasterList từ màn Giám sát thiết bị.

    Quy tắc đã chốt:
    - Device.org_unit chỉ là vị trí/đơn vị quản lý thiết bị, KHÔNG phải phạm vi nhân sự chấm trên máy.
    - Nếu đang lọc 1 đơn vị: chỉ tính lại đơn vị đó, nhưng vẫn kiểm tra đơn vị/ngày có AttendanceCommit hay chưa.
    - Nếu không lọc đơn vị: tính lại TẤT CẢ đơn vị có AttendanceCommit trong ngày.
    - Compute vẫn là commit-only: không có AttendanceCommit thì không tạo MasterList.
    """
    if request.method != "POST":
        return redirect("attendance_devices_v2:giam_sat_thiet_bi")

    work_date = _parse_date(request.POST.get("date")) or dj_timezone.localdate()
    unit_raw = (request.POST.get("unit") or "").strip()

    commit_qs = AttendanceCommit.objects.filter(work_date=work_date)

    if unit_raw.isdigit():
        requested_unit_id = int(unit_raw)
        unit_ids = [requested_unit_id]
        commit_unit_ids = set(
            commit_qs.filter(unit_id=requested_unit_id).values_list("unit_id", flat=True)
        )
    else:
        unit_ids = list(
            commit_qs
            .values_list("unit_id", flat=True)
            .distinct()
            .order_by("unit_id")
        )
        commit_unit_ids = set(unit_ids)

    if not unit_ids:
        messages.warning(
            request,
            f"Ngày {work_date:%Y-%m-%d} chưa có công chốt của đơn vị nào nên chưa thể tính MasterList."
        )
        next_url = (request.POST.get("next") or "").strip()
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect("attendance_devices_v2:giam_sat_thiet_bi")

    ok = 0
    no_commit = 0
    failed = 0
    rows_upserted = 0
    detail_notes: list[str] = []

    unit_symbols = dict(
        OrgUnit.objects.filter(id__in=unit_ids).values_list("id", "symbol")
    )

    for unit_id in unit_ids:
        symbol = unit_symbols.get(unit_id) or f"unit {unit_id}"
        if unit_id not in commit_unit_ids:
            no_commit += 1
            detail_notes.append(f"{symbol}: chưa có công chốt")
            continue

        compute_run_id = f"monitor-{work_date:%Y%m%d}-{unit_id}-{uuid4().hex[:8]}"
        try:
            res = compute_master_list_for_unit_date(
                unit_id=unit_id,
                work_date=work_date,
                compute_run_id=compute_run_id,
                compute_version=1,
            )
            if res.commit_id:
                ok += 1
                rows_upserted += int(res.master_rows_upserted or 0)
                if getattr(res, "notes", ""):
                    detail_notes.append(f"{symbol}: {res.master_rows_upserted} dòng; {res.notes}")
            else:
                # Phòng trường hợp commit bị xóa giữa lúc kiểm tra và compute.
                no_commit += 1
                detail_notes.append(f"{symbol}: chưa có công chốt")
        except Exception as exc:
            failed += 1
            detail_notes.append(f"{symbol}: lỗi {exc}")

    if unit_raw.isdigit():
        scope_text = f"đơn vị {unit_symbols.get(int(unit_raw), unit_raw)}"
    else:
        scope_text = "tất cả đơn vị có công chốt"

    msg = (
        f"Đã tính lại MasterList ngày {work_date:%Y-%m-%d} cho {scope_text}: "
        f"{ok} đơn vị có công chốt, cập nhật {rows_upserted} dòng."
    )
    if no_commit:
        msg += f" {no_commit} đơn vị chưa có công chốt."
    if failed:
        msg += f" {failed} đơn vị lỗi."
    if detail_notes:
        msg += " Chi tiết: " + " | ".join(detail_notes[:8])
        if len(detail_notes) > 8:
            msg += f" | còn {len(detail_notes) - 8} ghi chú khác."

    if failed or no_commit:
        messages.warning(request, msg)
    else:
        messages.success(request, msg)

    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("attendance_devices_v2:giam_sat_thiet_bi")


@login_required
@permission_required("attendance_devices_v2.change_attendancedevicev2", raise_exception=True)
@require_POST
def xoa_raw_chua_map_view(request):
    """
    Xóa raw chưa map card_id.

    Chỉ xóa raw thỏa điều kiện rất chặt:
    - normalized_at IS NULL;
    - normalized_punch IS NULL;
    - có device_user_id;
    - device_user_id chưa tồn tại trong Employee.card_id tại thời điểm xóa.

    Dùng cho dữ liệu test/rác hoặc UID chắc chắn không thuộc nhân sự.
    Nếu UID là của nhân sự thật, nên cập nhật Employee.card_id rồi Normalize lại, không xóa.
    """
    next_url = (request.POST.get("next") or "").strip()
    if not next_url.startswith("/"):
        next_url = None

    mode = (request.POST.get("mode") or "group").strip()
    qs = _unmapped_raw_qs().filter(normalized_punch_id__isnull=True)

    if mode == "all":
        confirm_text = (request.POST.get("confirm_text") or "").strip()
        if confirm_text != "XOA_RAW_CHUA_MAP":
            messages.error(request, "Chưa xác nhận đúng. Không xóa raw chưa map.")
            return redirect(next_url or "attendance_devices_v2:giam_sat_thiet_bi")
    else:
        device_id = (request.POST.get("device_id") or "").strip()
        uid = (request.POST.get("uid") or "").strip()
        if not device_id.isdigit() or not uid:
            messages.error(request, "Thiếu device_id hoặc UID cần xóa.")
            return redirect(next_url or "attendance_devices_v2:giam_sat_thiet_bi")
        qs = qs.filter(device_id=int(device_id), device_user_id=uid)

    count = qs.count()
    if count <= 0:
        messages.warning(request, "Không có raw chưa map phù hợp để xóa.")
        return redirect(next_url or "attendance_devices_v2:giam_sat_thiet_bi")

    deleted_count, _ = qs.delete()
    messages.success(request, f"Đã xóa {deleted_count} raw chưa map card_id. Sau đó có thể chạy Normalize lại để kiểm tra còn tồn không.")
    return redirect(next_url or "attendance_devices_v2:giam_sat_thiet_bi")


@login_required
@permission_required("attendance_devices_v2.view_attendancedevicev2", raise_exception=True)
def giam_sat_thiet_bi_view(request):
    """
    Dashboard vận hành thiết bị chấm công.

    Mục tiêu:
    - không thay thế màn CRUD Thiết bị/Agent;
    - giúp IT/HR Admin thấy máy nào online/offline/chậm dữ liệu;
    - thấy nhanh raw hôm nay, raw chưa normalize, UID chưa map và ingest log gần nhất.
    """
    today = dj_timezone.localdate()
    work_date = _parse_date(request.GET.get("date")) or today

    q = (request.GET.get("q") or "").strip()
    agent_raw = (request.GET.get("agent") or "").strip()
    unit_raw = (request.GET.get("unit") or "").strip()
    active_raw = (request.GET.get("active") or "1").strip()
    status_filter = (request.GET.get("status") or "").strip().upper()
    page_size = _safe_int(request.GET.get("page_size") or "100", 100)
    if page_size not in (50, 100, 200):
        page_size = 100

    tz = dj_timezone.get_current_timezone()
    day_start_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(0, 0, 0)), tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(datetime_timezone.utc)
    day_end_utc = day_end_local.astimezone(datetime_timezone.utc)
    since_24h = dj_timezone.now() - timedelta(hours=24)

    devices_qs = AttendanceDeviceV2.objects.select_related("assigned_agent", "org_unit").order_by("name")

    if q:
        devices_qs = devices_qs.filter(
            Q(name__icontains=q) |
            Q(host__icontains=q) |
            Q(model__icontains=q) |
            Q(serial_no__icontains=q) |
            Q(org_unit__symbol__icontains=q) |
            Q(org_unit__name__icontains=q)
        )
    if agent_raw.isdigit():
        devices_qs = devices_qs.filter(assigned_agent_id=int(agent_raw))
    if unit_raw.isdigit():
        devices_qs = devices_qs.filter(org_unit_id=int(unit_raw))
    if active_raw in {"0", "1"}:
        devices_qs = devices_qs.filter(is_active=(active_raw == "1"))

    # Lấy ingest log mới nhất bằng Subquery để tránh quét toàn bộ AttendanceIngestLogV2
    # rồi loop trong Python. Khi log tăng nhiều, đoạn cũ là một nguyên nhân gây chậm.
    latest_log_subquery = (
        AttendanceIngestLogV2.objects
        .filter(device_id=OuterRef("pk"))
        .order_by("-started_at", "-id")
        .values("id")[:1]
    )
    latest_status_subquery = (
        AttendanceDeviceStatusReportV2.objects
        .filter(device_id=OuterRef("pk"))
        .order_by("-reported_at", "-id")
        .values("id")[:1]
    )
    latest_backfill_subquery = (
        AttendanceDeviceBackfillReportV2.objects
        .filter(device_id=OuterRef("pk"))
        .order_by("-reported_at", "-id")
        .values("id")[:1]
    )
    devices_qs = devices_qs.annotate(
        _latest_log_id=Subquery(latest_log_subquery),
        _latest_status_id=Subquery(latest_status_subquery),
        _latest_backfill_id=Subquery(latest_backfill_subquery),
    )

    devices = list(devices_qs)
    device_ids = [d.id for d in devices]

    if not device_ids:
        agents = AttendanceDeviceAgentV2.objects.order_by("name")
        units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")
        return render(request, "backoffice/attendance_devices_v2/giam_sat_thiet_bi.html", {
            "work_date": work_date.strftime("%Y-%m-%d"),
            "q": q,
            "agent": agent_raw,
            "unit": unit_raw,
            "active": active_raw,
            "status": status_filter,
            "page_size": page_size,
            "agents": agents,
            "units": units,
            "rows": [],
            "kpi": {
                "total": 0, "online": 0, "stale": 0, "offline": 0, "unknown": 0, "disabled": 0,
                "raw_today": 0, "raw_pending": 0, "unresolved_today": 0, "unresolved_raw_today": 0,
                "normalized_today": 0, "agent_offline": 0, "realtime_error": 0, "backfill_failed": 0,
            },
            "status_links": [],
            "unmapped_uid_details": [],
            "unmapped_uid_page": None,
            "unmapped_uid_page_items": [],
            "unmapped_uid_total_groups": 0,
            "unmapped_uid_total_raw": 0,
            "uid_page_size": 20,
            "uid_q": "",
            "online_minutes": ONLINE_MINUTES,
            "stale_minutes": STALE_MINUTES,
            "agent_online_minutes": AGENT_ONLINE_MINUTES,
        })

    raw_today_counts = _dict_counts(
        AttendanceRawPunchV2.objects
        .filter(device_id__in=device_ids, event_time_utc__gte=day_start_utc, event_time_utc__lt=day_end_utc)
        .values("device_id").annotate(cnt=Count("id")),
        "device_id",
    )
    raw_24h_counts = _dict_counts(
        AttendanceRawPunchV2.objects
        .filter(device_id__in=device_ids, ingested_at__gte=since_24h)
        .values("device_id").annotate(cnt=Count("id")),
        "device_id",
    )
    raw_pending_counts = _dict_counts(
        AttendanceRawPunchV2.objects
        .filter(device_id__in=device_ids, normalized_at__isnull=True)
        .values("device_id").annotate(cnt=Count("id")),
        "device_id",
    )
    # Không load toàn bộ Employee.card_id vào Python rồi nhét vào IN (...).
    # Dùng subquery để DB tự so khớp UID chưa map, tránh chậm khi danh sách nhân sự lớn.
    unmapped_today_qs = (
        _unmapped_raw_qs()
        .filter(
            device_id__in=device_ids,
            event_time_utc__gte=day_start_utc,
            event_time_utc__lt=day_end_utc,
        )
    )

    unresolved_today_counts = _dict_counts(
        unmapped_today_qs
        .values("device_id")
        .annotate(cnt=Count("device_user_id", distinct=True)),
        "device_id",
    )
    unresolved_raw_today_counts = _dict_counts(
        unmapped_today_qs
        .values("device_id")
        .annotate(cnt=Count("id")),
        "device_id",
    )

    unresolved_uid_samples_by_device: dict[int, list[dict]] = {}
    for item in (
        unmapped_today_qs
        .values("device_id", "device_user_id")
        .annotate(cnt=Count("id"), last_seen=Max("event_time_local"))
        .order_by("device_id", "-cnt", "device_user_id")
    ):
        did = item["device_id"]
        if did is None:
            continue
        unresolved_uid_samples_by_device.setdefault(int(did), []).append({
            "uid": item["device_user_id"],
            "cnt": item["cnt"],
            "last_seen": item["last_seen"],
        })
    normalized_today_counts = _dict_counts(
        AttendanceNormalizedPunchV2.objects
        .filter(best_device_id__in=device_ids, canonical_time_utc__gte=day_start_utc, canonical_time_utc__lt=day_end_utc)
        .values("best_device_id").annotate(cnt=Count("id")),
        "best_device_id",
    )

    latest_log_ids = [getattr(d, "_latest_log_id", None) for d in devices if getattr(d, "_latest_log_id", None)]
    latest_logs: dict[int, AttendanceIngestLogV2] = {
        log.device_id: log
        for log in AttendanceIngestLogV2.objects.filter(id__in=latest_log_ids).select_related("agent")
    }
    latest_status_ids = [getattr(d, "_latest_status_id", None) for d in devices if getattr(d, "_latest_status_id", None)]
    latest_status_reports: dict[int, AttendanceDeviceStatusReportV2] = {
        rep.device_id: rep
        for rep in AttendanceDeviceStatusReportV2.objects.filter(id__in=latest_status_ids).select_related("agent")
    }
    latest_backfill_ids = [getattr(d, "_latest_backfill_id", None) for d in devices if getattr(d, "_latest_backfill_id", None)]
    latest_backfill_reports: dict[int, AttendanceDeviceBackfillReportV2] = {
        rep.device_id: rep
        for rep in AttendanceDeviceBackfillReportV2.objects.filter(id__in=latest_backfill_ids).select_related("agent")
    }

    now = dj_timezone.now()
    rows: list[DeviceMonitorRow] = []
    kpi = {
        "total": 0,
        "online": 0,
        "stale": 0,
        "offline": 0,
        "unknown": 0,
        "disabled": 0,
        "raw_today": 0,
        "raw_pending": 0,
        "unresolved_today": 0,
        "unresolved_raw_today": 0,
        "normalized_today": 0,
        "agent_offline": 0,
        "realtime_error": 0,
        "backfill_failed": 0,
    }

    for d in devices:
        latest_status = latest_status_reports.get(d.id)
        latest_backfill = latest_backfill_reports.get(d.id)
        dyn_status, dyn_label, dyn_class = _device_status_from_report(d, latest_status, now)
        realtime_label, realtime_class = _realtime_badge(latest_status, now)
        backfill_label, backfill_class = _backfill_badge(latest_backfill)
        agent_status, agent_label = _agent_status(d.assigned_agent, now)

        if status_filter and dyn_status != status_filter:
            continue

        raw_today = raw_today_counts.get(d.id, 0)
        raw_24h = raw_24h_counts.get(d.id, 0)
        raw_pending = raw_pending_counts.get(d.id, 0)
        unresolved_today = unresolved_today_counts.get(d.id, 0)
        unresolved_raw_today = unresolved_raw_today_counts.get(d.id, 0)
        unresolved_samples = _short_uid_list(unresolved_uid_samples_by_device.get(d.id, []))
        normalized_today = normalized_today_counts.get(d.id, 0)
        last_log = latest_logs.get(d.id)

        if last_log is None:
            log_label = "Chưa có log"
            log_class = "secondary"
        elif last_log.success:
            log_label = "OK"
            log_class = "success"
        else:
            log_label = "Lỗi"
            log_class = "danger"

        cursor = d.last_cursor_json or {}
        cursor_text = ""
        if isinstance(cursor, dict) and cursor:
            # Hiển thị gọn vài key đầu, tránh làm vỡ bảng.
            parts = []
            for idx, (key, val) in enumerate(cursor.items()):
                if idx >= 3:
                    parts.append("...")
                    break
                parts.append(f"{key}: {val}")
            cursor_text = "; ".join(parts)
        elif cursor:
            cursor_text = str(cursor)
        else:
            cursor_text = "-"

        rows.append(DeviceMonitorRow(
            device=d,
            dynamic_status=dyn_status,
            dynamic_status_label=dyn_label,
            dynamic_status_class=dyn_class,
            last_pull_ago=_ago(d.last_pull_at),
            agent_status=agent_status,
            agent_status_label=agent_label,
            agent_last_seen_ago=_ago(d.assigned_agent.last_seen_at) if d.assigned_agent else "-",
            raw_today=raw_today,
            raw_24h=raw_24h,
            raw_pending=raw_pending,
            unresolved_today=unresolved_today,
            unresolved_raw_today=unresolved_raw_today,
            unresolved_samples=unresolved_samples,
            normalized_today=normalized_today,
            last_log=last_log,
            last_log_status_label=log_label,
            last_log_class=log_class,
            latest_status=latest_status,
            latest_backfill=latest_backfill,
            realtime_label=realtime_label,
            realtime_class=realtime_class,
            backfill_label=backfill_label,
            backfill_class=backfill_class,
            drift_text=_drift_text(latest_status),
            last_error_text=(latest_status.last_error if latest_status and latest_status.last_error else (latest_backfill.error_message if latest_backfill and latest_backfill.error_message else "")),
            cursor_text=cursor_text,
        ))

        kpi["total"] += 1
        if dyn_status == "ONLINE":
            kpi["online"] += 1
        elif dyn_status == "STALE":
            kpi["stale"] += 1
        elif dyn_status == "OFFLINE":
            kpi["offline"] += 1
        elif dyn_status == "DISABLED":
            kpi["disabled"] += 1
        else:
            kpi["unknown"] += 1
        if agent_status in {"OFFLINE", "UNKNOWN", "NO_AGENT", "DISABLED"}:
            kpi["agent_offline"] += 1
        if latest_status and latest_status.realtime_status in {"ERROR", "OFFLINE", "REALTIME_UNAVAILABLE"}:
            kpi["realtime_error"] += 1
        if latest_backfill and latest_backfill.status in {"FAILED", "PARTIAL_PENDING"}:
            kpi["backfill_failed"] += 1
        kpi["raw_today"] += raw_today
        kpi["raw_pending"] += raw_pending
        kpi["unresolved_today"] += unresolved_today
        kpi["unresolved_raw_today"] += unresolved_raw_today
        kpi["normalized_today"] += normalized_today

    # Với số lượng máy nhỏ, phân trang chưa cần; vẫn giới hạn nếu sau này nhiều thiết bị.
    rows = rows[:page_size]

    # Bảng chi tiết UID chưa map: lấy TOÀN BỘ raw chưa map theo bộ lọc thiết bị hiện tại,
    # không chỉ ngày đang xem. Query được group + phân trang ở DB, tránh load toàn bộ raw vào Python.
    uid_q = (request.GET.get("uid_q") or "").strip()
    uid_page_size = _safe_int(request.GET.get("uid_page_size") or "20", 20)
    if uid_page_size not in (10, 20, 50):
        uid_page_size = 20

    unmapped_all_qs = _unmapped_raw_qs().filter(device_id__in=device_ids)
    if uid_q:
        unmapped_all_qs = unmapped_all_qs.filter(device_user_id__icontains=uid_q)

    unmapped_total_raw = unmapped_all_qs.count()
    unmapped_group_qs = (
        unmapped_all_qs
        .values("device_id", "device_user_id")
        .annotate(cnt=Count("id"), first_seen=Min("event_time_local"), last_seen=Max("event_time_local"))
        .order_by("device_id", "device_user_id")
    )

    unmapped_uid_paginator = Paginator(unmapped_group_qs, uid_page_size)
    uid_page_number = request.GET.get("uid_page") or 1
    unmapped_uid_page = unmapped_uid_paginator.get_page(uid_page_number)

    page_device_ids = [x["device_id"] for x in unmapped_uid_page.object_list if x.get("device_id")]
    page_devices = {
        d.id: d
        for d in AttendanceDeviceV2.objects.filter(id__in=page_device_ids).select_related("org_unit")
    }
    unmapped_uid_page_items = []
    for item in unmapped_uid_page.object_list:
        device = page_devices.get(item["device_id"])
        if not device:
            continue
        unmapped_uid_page_items.append({
            "device": device,
            "uid": item["device_user_id"],
            "cnt": item["cnt"],
            "first_seen": item["first_seen"],
            "last_seen": item["last_seen"],
        })

    # Giữ biến cũ để template/logic khác không vỡ; bảng mới dùng unmapped_uid_page_items.
    unmapped_uid_details = unmapped_uid_page_items

    agents = AttendanceDeviceAgentV2.objects.order_by("name")
    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")

    query_base = {
        "date": f"{work_date:%Y-%m-%d}",
        "q": q,
        "agent": agent_raw,
        "unit": unit_raw,
        "active": active_raw,
        "page_size": page_size,
    }
    status_links = []
    for code, label in [
        ("", "Tất cả"),
        ("ONLINE", "Online"),
        ("STALE", "Chậm"),
        ("OFFLINE", "Offline"),
        ("UNKNOWN", "Chưa có dữ liệu"),
        ("DISABLED", "Ngừng dùng"),
    ]:
        params = dict(query_base)
        if code:
            params["status"] = code
        status_links.append({"code": code, "label": label, "url": "?" + urlencode(params), "active": status_filter == code})

    return render(request, "backoffice/attendance_devices_v2/giam_sat_thiet_bi.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "q": q,
        "agent": agent_raw,
        "unit": unit_raw,
        "active": active_raw,
        "status": status_filter,
        "page_size": page_size,
        "agents": agents,
        "units": units,
        "rows": rows,
        "kpi": kpi,
        "status_links": status_links,
        "unmapped_uid_details": unmapped_uid_details,
        "unmapped_uid_page": unmapped_uid_page,
        "unmapped_uid_page_items": unmapped_uid_page_items,
        "unmapped_uid_total_groups": unmapped_uid_paginator.count,
        "unmapped_uid_total_raw": unmapped_total_raw,
        "uid_page_size": uid_page_size,
        "uid_q": uid_q,
        "online_minutes": ONLINE_MINUTES,
        "stale_minutes": STALE_MINUTES,
        "agent_online_minutes": AGENT_ONLINE_MINUTES,
    })
