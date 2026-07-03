from __future__ import annotations

from django.db.models import Q
from django.urls import reverse

from apps.hr.models import Employee

from .common import display_number, external_url_with_query, url_with_query


def build_daily_action_items(work_date, selected_unit_id, *, can_view_device_monitor=False, **kwargs):
    wd = work_date.isoformat()
    unit = selected_unit_id
    items = []

    def add(level, title, count, module, url, note=""):
        if count:
            items.append({"level": level, "title": title, "count": int(count), "module": module, "url": url, "note": note})

    add("danger", "Đơn vị chưa tạo bảng công", kwargs["missing_units"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", from_date=wd, to_date=wd, unit=unit, status="MISSING"))
    add("warning", "Đơn vị đang nháp, chưa chốt", kwargs["draft_units"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", from_date=wd, to_date=wd, unit=unit, status="DRAFT"))
    add("danger", "Nháp đã khóa nhưng chưa thấy công chốt", kwargs["locked_units"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", from_date=wd, to_date=wd, unit=unit, status="WARNING"))
    add("warning", "Người đăng ký làm nhưng chưa có mặt", kwargs["not_present_count"], "Chấm công", "#unit-presence-section", "Tính theo MasterList V2: có dữ liệu từ máy hoặc đã sửa thì tính hiện diện.")
    add("warning", "UID vân tay chưa khớp nhân sự", kwargs["unmapped_uid_count"], "Chấm công", external_url_with_query("attendance_devices_v2:giam_sat_thiet_bi") if can_view_device_monitor else None)
    add("warning", "Phiếu sửa công chờ phê duyệt", kwargs["pending_corrections"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", from_date=wd, to_date=wd, unit=unit) + "#corrections-section")
    add("danger", "Phiếu đã duyệt chưa áp dụng", kwargs["waiting_apply_corrections"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", from_date=wd, to_date=wd, unit=unit) + "#corrections-section")
    add("warning", "Thiết bị cần kiểm tra", kwargs["device_warnings"], "Quản lý chấm công", external_url_with_query("attendance_devices_v2:giam_sat_thiet_bi") if can_view_device_monitor else None)
    add("warning", "Dữ liệu đối chiếu cần tính lại", kwargs["stale_master"], "Quản lý chấm công", external_url_with_query("attendance_devices_v2:thong_ke", date=wd))
    add("warning", "Dòng công thiếu mốc chấm công", kwargs["missing_marks"], "Quản lý chấm công", external_url_with_query("attendance_devices_v2:thong_ke", date=wd))
    return sort_action_items(items)


def build_period_action_items(from_date, to_date, selected_unit_id, *, can_view_device_monitor=False, **kwargs):
    unit = selected_unit_id
    params = {"from_date": from_date.isoformat(), "to_date": to_date.isoformat(), "unit": unit}
    items = []

    def add(level, title, count, module, url, note=""):
        if count:
            items.append({"level": level, "title": title, "count": int(count), "module": module, "url": url, "note": note})

    add("danger", "Lượt đơn vị/ngày chưa tạo bảng công", kwargs["missing_unit_days"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", **params, status="MISSING"))
    add("warning", "Lượt đơn vị/ngày đang nháp", kwargs["draft_unit_days"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", **params, status="DRAFT"))
    add("danger", "Nháp khóa nhưng chưa thấy công chốt", kwargs["locked_unit_days"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", **params, status="WARNING"))
    add("warning", "Phiếu sửa công chờ phê duyệt", kwargs["pending_corrections"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", **params) + "#corrections-section")
    add("danger", "Phiếu đã duyệt chưa áp dụng", kwargs["waiting_apply_corrections"], "Quản lý công", url_with_query("backoffice:attendance_report_dashboard", **params) + "#corrections-section")
    add("warning", "Dữ liệu đối chiếu cần tính lại", kwargs["stale_master"], "Quản lý chấm công", reverse("attendance_devices_v2:thong_ke"))
    add("warning", "Dòng công thiếu mốc", kwargs["missing_marks"], "Quản lý chấm công", reverse("attendance_devices_v2:thong_ke"))
    add("warning", "UID vân tay chưa khớp nhân sự", kwargs["unmapped_uid_count"], "Quản lý chấm công", reverse("attendance_devices_v2:giam_sat_thiet_bi") if can_view_device_monitor else None)
    add("warning", "Thiết bị cần kiểm tra", kwargs["device_warnings"], "Quản lý chấm công", reverse("attendance_devices_v2:giam_sat_thiet_bi") if can_view_device_monitor else None)
    return sort_action_items(items)


def sort_action_items(items, limit=12):
    severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    items.sort(key=lambda x: (severity_order.get(x["level"], 9), -x["count"], x["title"]))
    return items[:limit]


def role_blocks(unit_ids, active_employee_count, unmapped_uid_count, pending_corrections, waiting_apply_corrections, assignment_count, *, can_view_device_monitor=False):
    hr_missing_card = Employee.objects.filter(status=Employee.Status.ACTIVE, unit_id__in=unit_ids).filter(Q(card_id__isnull=True) | Q(card_id="")).count()
    statistic_items = [
        {"label": "Phiếu chờ phê duyệt", "value": display_number(pending_corrections), "url": reverse("backoffice:attendance_report_dashboard") + "#corrections-section"},
        {"label": "Đã duyệt chưa áp dụng", "value": display_number(waiting_apply_corrections), "url": reverse("backoffice:attendance_report_dashboard") + "#corrections-section"},
    ]
    if can_view_device_monitor:
        statistic_items.append({"label": "UID vân tay chưa khớp", "value": display_number(unmapped_uid_count), "url": external_url_with_query("attendance_devices_v2:giam_sat_thiet_bi")})
    else:
        statistic_items.append({"label": "UID vân tay chưa khớp", "value": display_number(unmapped_uid_count), "url": None})
    return {
        "hr": {
            "title": "Nhân sự & dữ liệu nền",
            "items": [
                {"label": "Nhân sự ACTIVE", "value": display_number(active_employee_count), "url": reverse("backoffice:employee_list")},
                {"label": "Thiếu mã thẻ", "value": display_number(hr_missing_card), "url": reverse("backoffice:employee_list")},
                {"label": "Điều động hiệu lực hôm nay", "value": display_number(assignment_count), "url": reverse("backoffice:temp_assignment_list")},
            ],
        },
        "statistic": {
            "title": "Thống kê cần xử lý",
            "items": statistic_items,
        },
    }
