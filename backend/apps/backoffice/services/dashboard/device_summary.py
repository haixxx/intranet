from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time as dt_time, timedelta, timezone as datetime_timezone

from django.db.models import Q
from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from apps.attendance_devices_v2.models import (
    AttendanceDeviceStatusReportV2,
    AttendanceDeviceV2,
    AttendanceRawPunchV2,
)
from apps.attendance_devices_v2.models_master_list import AttendanceDeviceMasterListV2
from apps.hr.models import Employee

from .common import period_bounds_local, unit_symbol


DEVICE_ONLINE_MINUTES = 10
DEVICE_STALE_MINUTES = 60


def raw_presence_sets(unit_ids: list[int], start_dt, end_dt, extra_employee_ids=None):
    """
    Dữ liệu vân tay thô: raw.device_user_id khớp Employee.card_id.

    Hàm này chỉ dùng để đếm UID vân tay chưa khớp nhân sự / thống kê kỹ thuật.
    KPI hiện diện của dashboard tổng quan không quét raw trực tiếp.
    """
    raw_qs = AttendanceRawPunchV2.objects.filter(event_time_local__gte=start_dt, event_time_local__lte=end_dt)
    raw_pairs = list(raw_qs.values_list("device_user_id", "event_time_local"))
    raw_uids = {str(uid).strip() for uid, _ in raw_pairs if str(uid or "").strip()}

    extra_employee_ids = set(extra_employee_ids or [])
    employee_filter = Q(unit_id__in=unit_ids)
    if extra_employee_ids:
        employee_filter = employee_filter | Q(id__in=extra_employee_ids)
    employees = list(
        Employee.objects.filter(card_id__in=raw_uids, status=Employee.Status.ACTIVE)
        .filter(employee_filter)
        .select_related("unit")
        .only("id", "card_id", "unit_id")
    )
    card_to_employee = {str(e.card_id).strip(): e for e in employees if str(e.card_id or "").strip()}
    all_known_cards = set(
        Employee.objects.exclude(card_id__isnull=True)
        .exclude(card_id="")
        .values_list("card_id", flat=True)
    )
    all_known_cards = {str(x).strip() for x in all_known_cards if str(x or "").strip()}

    unit_id_set = set(unit_ids)
    present_employee_ids: set[int] = set()
    present_by_unit: dict[int, set[int]] = defaultdict(set)
    for uid in raw_uids:
        employee = card_to_employee.get(uid)
        if not employee:
            continue
        if employee.unit_id not in unit_id_set and employee.id not in extra_employee_ids:
            continue
        present_employee_ids.add(employee.id)
        present_by_unit[employee.unit_id].add(employee.id)

    unmapped_uids = {uid for uid in raw_uids if uid not in all_known_cards}
    return present_employee_ids, present_by_unit, len(unmapped_uids), len(raw_pairs)


def daily_present_by_work_date(unit_ids: list[int], dates: list, extra_employee_ids=None):
    start_dt, end_dt = period_bounds_local(dates[0], dates[-1])
    raw_pairs = list(
        AttendanceRawPunchV2.objects.filter(event_time_local__gte=start_dt, event_time_local__lte=end_dt)
        .values_list("device_user_id", "event_time_local")
    )
    raw_uids = {str(uid).strip() for uid, _ in raw_pairs if str(uid or "").strip()}
    extra_employee_ids = set(extra_employee_ids or [])
    employee_filter = Q(unit_id__in=unit_ids)
    if extra_employee_ids:
        employee_filter = employee_filter | Q(id__in=extra_employee_ids)
    employees = Employee.objects.filter(card_id__in=raw_uids, status=Employee.Status.ACTIVE).filter(employee_filter).only("id", "card_id")
    card_to_emp_id = {str(e.card_id).strip(): e.id for e in employees if str(e.card_id or "").strip()}

    date_set = set(dates)
    result: dict = {d: set() for d in dates}
    for uid, event_dt in raw_pairs:
        emp_id = card_to_emp_id.get(str(uid or "").strip())
        if not emp_id:
            continue
        event_date = timezone.localtime(event_dt).date() if timezone.is_aware(event_dt) else event_dt.date()
        if event_date in date_set:
            result[event_date].add(emp_id)
    return result


def _get_window_minutes() -> int:
    settings = AttendanceSettings.objects.first()
    if settings and getattr(settings, "window_minutes", None):
        try:
            return int(settings.window_minutes)
        except Exception:
            return 60
    return 60


def _work_date_bounds_utc(work_date, *, window_minutes: int) -> tuple[datetime, datetime]:
    """Khoảng ngày công giống màn Thống kê V2: có tính ca qua ngày."""
    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(datetime.combine(work_date, dt_time(0, 0)), tz) - timedelta(minutes=window_minutes)
    end_local = timezone.make_aware(datetime.combine(work_date + timedelta(days=1), dt_time(8, 0)), tz) + timedelta(minutes=window_minutes)
    return start_local.astimezone(datetime_timezone.utc), end_local.astimezone(datetime_timezone.utc)


def _mark_from_machine_or_corrected(row: AttendanceDeviceMasterListV2, field: str):
    """
    Trả về mốc hiện diện theo MasterList V2.

    - actual_*  : nguồn từ máy/đã compute.
    - override_*: nguồn đã sửa, mặc định thường copy từ actual nhưng có thể khác khi HR sửa.

    Dashboard tổng quan chỉ cần biết người đó đã có ít nhất một dấu hiệu
    hiện diện, không yêu cầu đủ mốc và không loại người đi muộn/về sớm.
    """
    return getattr(row, f"actual_{field}_local", None) or getattr(row, f"override_{field}_local", None)


def _has_any_masterlist_presence_mark(row: AttendanceDeviceMasterListV2) -> bool:
    checks = []
    if row.expected_in1:
        checks.append(_mark_from_machine_or_corrected(row, "in1"))
    if row.expected_out1:
        checks.append(_mark_from_machine_or_corrected(row, "out1"))
    if row.expected_in2:
        checks.append(_mark_from_machine_or_corrected(row, "in2"))
    if row.expected_out2:
        checks.append(_mark_from_machine_or_corrected(row, "out2"))
    return any(x is not None for x in checks)


def masterlist_presence_by_work_date(unit_ids: list[int], dates: list, extra_employee_ids=None):
    """
    Hiện diện từ MasterList V2.

    Quy ước dashboard tổng quan:
    - Có mặt/hiện diện = có ít nhất một mốc từ máy (actual_*) hoặc đã sửa
      (override_*) trên dòng MasterList V2.
    - Không yêu cầu đủ mốc. Người đi muộn/về sớm/thiếu mốc vẫn là người
      đã hiện diện, còn vi phạm được xử lý ở báo cáo đối chiếu chi tiết.
    - Không quét raw để tính KPI hiện diện nhằm giữ dashboard nhẹ.
    """
    result: dict = {d: set() for d in dates}
    if not unit_ids or not dates:
        return result, 0

    extra_employee_ids = set(extra_employee_ids or [])
    rows = list(
        AttendanceDeviceMasterListV2.objects.filter(unit_id__in=unit_ids, work_date__in=dates)
        .filter(Q(employee__unit_id__in=unit_ids) | Q(employee_id__in=extra_employee_ids))
        .only(
            "id", "work_date", "unit_id", "employee_id", "is_exempt", "expected_marks",
            "expected_in1", "expected_out1", "expected_in2", "expected_out2",
            "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
            "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
        )
    )
    if not rows:
        return result, 0

    for row in rows:
        if row.is_exempt or row.expected_marks <= 0:
            continue
        if _has_any_masterlist_presence_mark(row) and row.work_date in result:
            result[row.work_date].add(row.employee_id)

    return result, len(rows)

def latest_device_status(device: AttendanceDeviceV2):
    return device.status_reports_v2.order_by("-reported_at", "-id").first()


def device_health_summary(unit_ids: list[int]):
    now = timezone.now()
    devices = list(AttendanceDeviceV2.objects.filter(is_active=True).select_related("org_unit", "assigned_agent"))
    if unit_ids:
        unit_id_set = set(unit_ids)
        devices = [d for d in devices if not d.org_unit_id or d.org_unit_id in unit_id_set]
    rows = []
    online = 0
    warning = 0
    for device in devices:
        latest = latest_device_status(device)
        status_key = "UNKNOWN"
        label = "Chưa có dữ liệu"
        badge = "secondary"
        ref_dt = None
        if latest:
            ref_dt = latest.last_device_seen_at or latest.last_realtime_at or latest.reported_at
        elif device.last_pull_at:
            ref_dt = device.last_pull_at

        if not ref_dt:
            status_key, label, badge = "UNKNOWN", "Chưa có dữ liệu", "secondary"
        else:
            age_min = max(0, (now - ref_dt).total_seconds() / 60)
            if latest and age_min <= DEVICE_STALE_MINUTES:
                if age_min > DEVICE_ONLINE_MINUTES:
                    status_key, label, badge = "STALE", "Chậm realtime", "warning"
                elif latest.realtime_status == AttendanceDeviceStatusReportV2.RealtimeStatus.ONLINE:
                    status_key, label, badge = "ONLINE", "Online", "success"
                elif latest.realtime_status in (
                    AttendanceDeviceStatusReportV2.RealtimeStatus.RECONNECTING,
                    AttendanceDeviceStatusReportV2.RealtimeStatus.PAUSED_BACKFILL,
                    AttendanceDeviceStatusReportV2.RealtimeStatus.PAUSED_TIME_SYNC,
                ):
                    status_key, label, badge = "STALE", latest.get_realtime_status_display(), "warning"
                else:
                    status_key, label, badge = "OFFLINE", latest.get_realtime_status_display(), "danger"
            else:
                if age_min <= DEVICE_ONLINE_MINUTES:
                    status_key, label, badge = "ONLINE", "Online", "success"
                elif age_min <= DEVICE_STALE_MINUTES:
                    status_key, label, badge = "STALE", "Chậm dữ liệu", "warning"
                else:
                    status_key, label, badge = "OFFLINE", "Offline", "danger"
        if status_key == "ONLINE":
            online += 1
        elif status_key in ("OFFLINE", "STALE", "UNKNOWN"):
            warning += 1
            rows.append({
                "device": device.name,
                "unit": unit_symbol(device.org_unit),
                "status": label,
                "badge": badge,
                "last_seen": ref_dt,
                "last_seen_label": timezone.localtime(ref_dt).strftime("%d/%m %H:%M") if ref_dt else "—",
            })
    return {
        "total": len(devices),
        "online": online,
        "warnings": warning,
        "rows": rows[:5],
    }


def masterlist_issue_count(unit_ids: list[int], from_date, to_date):
    qs = AttendanceDeviceMasterListV2.objects.filter(unit_id__in=unit_ids, work_date__gte=from_date, work_date__lte=to_date)
    stale = qs.filter(compute_state=AttendanceDeviceMasterListV2.ComputeState.STALE).count()
    missing = qs.filter(missing_marks__gt=0).count()
    return stale, missing
