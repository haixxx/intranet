from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from apps.backoffice.services.access_scope import (
    get_allowed_attendance_units as _scoped_attendance_units,
    resolve_attendance_unit_scope,
)


def parse_date(value: str | None):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def date_range(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)


def decimal_value(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0.00")


def display_number(value, digits: int = 1):
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return f"{int(value):,}".replace(",", ".")
        return f"{float(value):,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}".replace(",", ".")
        return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return str(value)


def percent_value(numerator: int | Decimal | float, denominator: int | Decimal | float) -> float | None:
    try:
        denominator = float(denominator)
        if denominator <= 0:
            return None
        return round(float(numerator) * 100.0 / denominator, 1)
    except Exception:
        return None


def url_with_query(view_name: str, **params) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    base = reverse(view_name)
    return f"{base}?{urlencode(clean)}" if clean else base


def external_url_with_query(view_name: str, **params) -> str:
    # Alias giữ tên cũ để đọc code rõ hơn khi link sang module khác.
    return url_with_query(view_name, **params)


def get_allowed_attendance_units(user):
    return _scoped_attendance_units(user)


def resolve_unit_scope(user, selected_unit_id: int | None = None):
    return resolve_attendance_unit_scope(user, selected_unit_id)


def unit_symbol(unit) -> str:
    if not unit:
        return "—"
    return getattr(unit, "symbol", "") or getattr(unit, "code", "") or str(unit.pk)


def unit_label(unit) -> str:
    if not unit:
        return "—"
    symbol = unit_symbol(unit)
    name = getattr(unit, "name", "") or ""
    return f"{symbol} - {name}" if name else symbol


def work_date_bounds_local(work_date):
    """
    Hàm phụ cho dữ liệu vân tay thô theo ngày lịch.
    KPI hiện diện lấy từ MasterList V2; raw chỉ dùng cho thống kê kỹ thuật như UID chưa khớp.
    """
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(work_date, dt_time(0, 0)), tz)
    end = timezone.make_aware(datetime.combine(work_date, dt_time(23, 59, 59, 999999)), tz)
    return start, end


def period_bounds_local(from_date, to_date):
    start, _ = work_date_bounds_local(from_date)
    _, end = work_date_bounds_local(to_date)
    return start, end


def can_view_device_monitor(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.has_perm("attendance_devices_v2.view_attendancedevicev2")


def quick_links(user=None):
    links = [
        {"label": "Quản lý công", "url": reverse("backoffice:attendance_report_dashboard"), "icon": "ti-report-analytics"},
        {"label": "Quản lý chấm công", "url": reverse("attendance_devices_v2:bao_cao"), "icon": "ti-fingerprint"},
    ]
    if user is None or can_view_device_monitor(user):
        links.append({"label": "Giám sát thiết bị", "url": reverse("attendance_devices_v2:giam_sat_thiet_bi"), "icon": "ti-activity-heartbeat"})
    links.append({"label": "Nhân sự", "url": reverse("backoffice:employee_list"), "icon": "ti-address-book"})
    return links
