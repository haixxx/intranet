from __future__ import annotations

from django.urls import reverse
from django.db.models import Count

from apps.hr.models import Employee

from .alerts import build_daily_action_items, role_blocks
from .common import (
    display_number,
    percent_value,
    can_view_device_monitor,
    quick_links,
    resolve_unit_scope,
    unit_label,
    unit_symbol,
    url_with_query,
    work_date_bounds_local,
)
from .device_summary import device_health_summary, masterlist_issue_count, masterlist_presence_by_work_date, raw_presence_sets
from .work_summary import assignment_counts, build_planned_data, committed_role_people_counts, correction_counts, get_source_items


class OverviewDailyService:
    def __init__(self, request, work_date, selected_unit_id: int | None = None):
        self.request = request
        self.work_date = work_date
        self.allowed_units, self.selected_unit_id, self.units, self.unit_ids = resolve_unit_scope(
            request.user,
            selected_unit_id,
        )

    def build(self) -> dict:
        if not self.unit_ids:
            return self._empty_context()

        user_can_view_device_monitor = can_view_device_monitor(self.request.user)

        commit_items, batch_items, commit_keys, batch_keys, locked_keys = get_source_items(self.unit_ids, self.work_date, self.work_date)
        planned = build_planned_data(commit_items, batch_items)
        start_dt, end_dt = work_date_bounds_local(self.work_date)
        raw_present_ids, _present_by_base_unit, unmapped_uid_count, raw_count = raw_presence_sets(
            self.unit_ids,
            start_dt,
            end_dt,
            planned.roster_employee_ids,
        )
        master_present_by_date, master_row_count = masterlist_presence_by_work_date(
            self.unit_ids,
            [self.work_date],
            planned.roster_employee_ids,
        )
        present_ids = master_present_by_date.get(self.work_date, set())
        if master_row_count:
            presence_source_label = "MasterList V2: từ máy hoặc đã sửa"
        else:
            presence_source_label = "Chưa có dữ liệu đối chiếu chấm công"

        planned_ids = planned.work_employee_ids
        if planned_ids:
            present_registered_ids = present_ids.intersection(planned_ids)
            present_count = len(present_registered_ids)
            denominator = len(planned_ids)
        else:
            present_registered_ids = present_ids
            present_count = len(present_registered_ids)
            denominator = 0

        presence_rate = percent_value(present_count, denominator)
        not_present_count = max(0, denominator - present_count)
        active_by_unit = dict(
            Employee.objects.filter(status=Employee.Status.ACTIVE, unit_id__in=self.unit_ids)
            .values("unit_id")
            .annotate(total=Count("id"))
            .values_list("unit_id", "total")
        )
        active_employee_count = sum(active_by_unit.values())
        assignment_count, assignment_people = assignment_counts(self.unit_ids, self.work_date, self.work_date)
        committed_role_counts = committed_role_people_counts(self.unit_ids, self.work_date, self.work_date)
        pending_corrections, waiting_apply_corrections = correction_counts(self.unit_ids, self.work_date, self.work_date)
        stale_master, missing_marks = masterlist_issue_count(self.unit_ids, self.work_date, self.work_date)
        device_summary = device_health_summary(self.unit_ids)

        unit_day_total = len(self.unit_ids)
        committed_units = len({uid for uid, _ in commit_keys})
        draft_units = len({uid for uid, _ in batch_keys})
        locked_units = len({uid for uid, _ in locked_keys})
        missing_units = max(0, unit_day_total - committed_units - draft_units - locked_units)

        unit_rows = self._build_daily_unit_rows(planned, present_ids, commit_keys, batch_keys, locked_keys, active_by_unit)
        action_items = build_daily_action_items(
            self.work_date,
            self.selected_unit_id,
            can_view_device_monitor=user_can_view_device_monitor,
            missing_units=missing_units,
            draft_units=draft_units,
            locked_units=locked_units,
            not_present_count=not_present_count,
            unmapped_uid_count=unmapped_uid_count,
            pending_corrections=pending_corrections,
            waiting_apply_corrections=waiting_apply_corrections,
            device_warnings=device_summary["warnings"],
            stale_master=stale_master,
            missing_marks=missing_marks,
        )

        kpis = [
            {
                "title": "Nhân sự hiệu lực",
                "value": display_number(active_employee_count),
                "subtext": "",
                "icon": "ti-users",
                "class": "primary",
                "url": reverse("backoffice:employee_list"),
            },
            {
                "title": "Sĩ số đăng ký làm",
                "value": display_number(len(planned_ids)),
                "subtext": "",
                "icon": "ti-clipboard-check",
                "class": "primary",
                "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.work_date.isoformat(), to_date=self.work_date.isoformat(), unit=self.selected_unit_id),
            },
            {
                "title": "Hiện diện thực tế",
                "value": f"{display_number(present_count)} ({presence_rate}%)" if presence_rate is not None else display_number(present_count),
                "subtext": "",
                "icon": "ti-fingerprint",
                "class": "success",
                "url": url_with_query("attendance_devices_v2:bao_cao", **{"from": self.work_date.isoformat(), "to": self.work_date.isoformat()}),
            },
            {
                "title": "Chưa có mặt",
                "value": display_number(not_present_count),
                "subtext": "",
                "icon": "ti-user-question",
                "class": "warning" if not_present_count else "success",
                "url": "#unit-presence-section",
            },
            {
                "title": "Điều động hôm nay",
                "value": display_number(assignment_people),
                "subtext": "",
                "icon": "ti-arrows-left-right",
                "class": "info",
                "url": reverse("backoffice:temp_assignment_list"),
            },
            {
                "title": "Việc cần xử lý",
                "value": display_number(sum(int(x["count"]) for x in action_items)),
                "subtext": "",
                "icon": "ti-alert-triangle",
                "class": "danger" if action_items else "success",
                "url": "#action-items-section",
            },
        ]

        chart_payload = {
            "mode": "daily",
            "unit_presence": [
                {
                    "unit": row["unit_symbol"],
                    "total": row["total_staff"],
                    "registered": row["planned"],
                    "present": row["present"],
                    "missing": row["not_present"],
                    "other": row["other"],
                }
                for row in unit_rows
            ],
            "unit_distribution": [
                {
                    "unit": row["unit_symbol"],
                    "total": row["total_staff"],
                }
                for row in unit_rows
                if row["total_staff"] > 0
            ],
            "commit_progress": {
                "labels": ["Đã chốt", "Đang nháp", "Chưa tạo", "Bất thường"],
                "values": [committed_units, draft_units, missing_units, locked_units],
            },
        }

        return {
            "page_title": "Tổng quan hệ thống",
            "mode": "daily",
            "filters": self._filters(),
            "kpis": kpis,
            "daily_status_cards": [
                {
                    "title": "Người công tác",
                    "value": display_number(committed_role_counts.get("business_trip", 0)),
                    "icon": "ti-briefcase",
                    "class": "primary",
                    "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.work_date.isoformat(), to_date=self.work_date.isoformat(), unit=self.selected_unit_id),
                },
                {
                    "title": "Người nghỉ ốm",
                    "value": display_number(committed_role_counts.get("sick_leave", 0)),
                    "icon": "ti-heartbeat",
                    "class": "warning",
                    "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.work_date.isoformat(), to_date=self.work_date.isoformat(), unit=self.selected_unit_id),
                },
                {
                    "title": "Người nghỉ phép",
                    "value": display_number(committed_role_counts.get("paid_leave", 0)),
                    "icon": "ti-calendar-check",
                    "class": "success",
                    "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.work_date.isoformat(), to_date=self.work_date.isoformat(), unit=self.selected_unit_id),
                },
            ],
            "unit_rows": unit_rows,
            "action_items": action_items,
            "device_summary": device_summary,
            "commit_progress": {
                "total": unit_day_total,
                "committed": committed_units,
                "draft": draft_units,
                "missing": missing_units,
                "locked": locked_units,
                "committed_rate": percent_value(committed_units, unit_day_total) or 0,
            },
            "role_blocks": role_blocks(
                self.unit_ids,
                active_employee_count,
                unmapped_uid_count,
                pending_corrections,
                waiting_apply_corrections,
                assignment_count,
                can_view_device_monitor=user_can_view_device_monitor,
            ),
            "chart_payload": chart_payload,
            "quick_links": quick_links(self.request.user),
        }

    def _filters(self):
        return {
            "mode": "daily",
            "work_date": self.work_date,
            "from_date": self.work_date,
            "to_date": self.work_date,
            "selected_unit_id": self.selected_unit_id or "",
            "units": self.allowed_units,
        }

    def _build_daily_unit_rows(self, planned, present_ids: set[int], commit_keys, batch_keys, locked_keys, active_by_unit: dict[int, int]):
        rows = []
        for unit in self.units:
            planned_ids = planned.work_by_unit.get(unit.id, set())
            present = len(planned_ids.intersection(present_ids)) if planned_ids else 0
            planned_count = len(planned_ids)
            not_present = max(0, planned_count - present)
            active_count = int(active_by_unit.get(unit.id, 0) or 0)
            # Tổng quân số dùng để thể hiện cột đơn vị trên dashboard.
            # Nếu có BS đến làm số đăng ký lớn hơn quân số biên chế, lấy số lớn hơn
            # để cột stack không bị âm phần "Khác".
            total_staff = max(active_count, present + not_present)
            other = max(0, total_staff - present - not_present)
            rate = percent_value(present, planned_count)
            if (unit.id, self.work_date) in commit_keys:
                status = "Đã chốt"
                badge = "bo-badge-success"
            elif (unit.id, self.work_date) in batch_keys:
                status = "Đang nháp"
                badge = "bo-badge-primary"
            elif (unit.id, self.work_date) in locked_keys:
                status = "Cần kiểm tra"
                badge = "bo-badge-danger"
            else:
                status = "Chưa tạo"
                badge = "bo-badge-secondary"
            rows.append({
                "unit_symbol": unit_symbol(unit),
                "unit_label": unit_label(unit),
                "total_staff": total_staff,
                "total_staff_label": display_number(total_staff),
                "planned": planned_count,
                "present": present,
                "present_label": f"{display_number(present)} ({rate}%)" if rate is not None else display_number(present),
                "not_present": not_present,
                "other": other,
                "presence_rate": rate,
                "presence_rate_label": f"{rate}%" if rate is not None else "—",
                "leave_count": planned.leave_by_unit.get(unit.id, 0),
                "status": status,
                "badge": badge,
                "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.work_date.isoformat(), to_date=self.work_date.isoformat(), unit=unit.id),
            })
        # Ưu tiên đơn vị có đăng ký công lên trước để biểu đồ/tables không bị
        # lấp bởi các đơn vị 0 dữ liệu khi phạm vi xem có nhiều đơn vị.
        rows.sort(key=lambda r: (
            0 if r["planned"] > 0 else 1,
            -r["planned"],
            -r["total_staff"],
            -r["not_present"],
            r["unit_symbol"],
        ))
        return rows

    def _empty_context(self):
        return {
            "page_title": "Tổng quan hệ thống",
            "mode": "daily",
            "filters": self._filters(),
            "kpis": [],
            "unit_rows": [],
            "action_items": [],
            "device_summary": {"total": 0, "online": 0, "warnings": 0, "rows": []},
            "commit_progress": {"total": 0, "committed": 0, "draft": 0, "missing": 0, "locked": 0, "committed_rate": 0},
            "role_blocks": {},
            "chart_payload": {"mode": "daily", "unit_presence": [], "commit_progress": {"labels": [], "values": []}},
            "quick_links": [],
        }
