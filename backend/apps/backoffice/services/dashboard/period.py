from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from .alerts import build_period_action_items
from .common import (
    date_range,
    decimal_value,
    display_number,
    percent_value,
    period_bounds_local,
    can_view_device_monitor,
    quick_links,
    resolve_unit_scope,
    unit_label,
    unit_symbol,
    url_with_query,
)
from .device_summary import device_health_summary, masterlist_issue_count, masterlist_presence_by_work_date, raw_presence_sets
from .work_summary import (
    assignment_counts,
    batch_item_is_work,
    batch_item_work_credit,
    build_planned_data,
    commit_item_is_work,
    commit_item_work_credit,
    correction_counts,
    get_source_items,
    item_include_in_unit,
)


class OverviewPeriodService:
    def __init__(self, request, from_date, to_date, selected_unit_id: int | None = None, group_by: str = "day"):
        self.request = request
        self.from_date = from_date
        self.to_date = to_date
        self.group_by = group_by if group_by in ("day", "unit") else "day"
        self.allowed_units, self.selected_unit_id, self.units, self.unit_ids = resolve_unit_scope(
            request.user,
            selected_unit_id,
        )
        self.days = list(date_range(from_date, to_date))

    def build(self) -> dict:
        if not self.unit_ids or not self.days:
            return self._empty_context()

        user_can_view_device_monitor = can_view_device_monitor(self.request.user)

        commit_items, batch_items, commit_keys, batch_keys, locked_keys = get_source_items(self.unit_ids, self.from_date, self.to_date)
        planned = build_planned_data(commit_items, batch_items)
        master_present_by_date, master_row_count = masterlist_presence_by_work_date(
            self.unit_ids,
            self.days,
            planned.roster_employee_ids,
        )
        present_by_date = master_present_by_date
        if master_row_count:
            presence_source_label = "MasterList V2: từ máy hoặc đã sửa"
        else:
            presence_source_label = "Chưa có dữ liệu đối chiếu chấm công"
        planned_by_date: dict = {d: set() for d in self.days}
        leave_by_date: dict = Counter()
        work_credit_by_date: dict = defaultdict(lambda: Decimal("0.00"))
        overtime_by_date: dict = defaultdict(lambda: Decimal("0.00"))
        leave_by_unit: dict = Counter()
        overtime_by_unit: dict = defaultdict(lambda: Decimal("0.00"))

        for item in commit_items:
            if not item_include_in_unit(item):
                continue
            d = item.commit.work_date
            uid = item.commit.unit_id
            if commit_item_is_work(item):
                planned_by_date[d].add(item.employee_id)
                work_credit_by_date[d] += commit_item_work_credit(item)
                ot = decimal_value(getattr(item, "overtime_hours", 0))
                overtime_by_date[d] += ot
                overtime_by_unit[uid] += ot
            else:
                leave_by_date[d] += 1
                leave_by_unit[uid] += 1
        for item in batch_items:
            if not item_include_in_unit(item):
                continue
            d = item.batch.work_date
            uid = item.batch.unit_id
            if batch_item_is_work(item):
                planned_by_date[d].add(item.employee_id)
                work_credit_by_date[d] += batch_item_work_credit(item)
                ot = decimal_value(getattr(item, "overtime_hours", 0))
                overtime_by_date[d] += ot
                overtime_by_unit[uid] += ot
            else:
                leave_by_date[d] += 1
                leave_by_unit[uid] += 1

        trend_presence = []
        trend_leave = []
        total_planned_person_days = 0
        total_present_registered = 0
        for d in self.days:
            planned_ids = planned_by_date.get(d, set())
            present_ids = present_by_date.get(d, set())
            present_registered = len(planned_ids.intersection(present_ids)) if planned_ids else 0
            planned_count = len(planned_ids)
            total_planned_person_days += planned_count
            total_present_registered += present_registered
            rate = percent_value(present_registered, planned_count)
            trend_presence.append({
                "date": d.strftime("%d/%m"),
                "planned": planned_count,
                "present": present_registered,
                "rate": rate or 0,
            })
            trend_leave.append({
                "date": d.strftime("%d/%m"),
                "leave": int(leave_by_date.get(d, 0)),
            })

        unit_day_total = len(self.unit_ids) * len(self.days)
        committed_unit_days = len(commit_keys)
        draft_unit_days = len(batch_keys)
        locked_unit_days = len(locked_keys)
        missing_unit_days = max(0, unit_day_total - committed_unit_days - draft_unit_days - locked_unit_days)
        pending_corrections, waiting_apply_corrections = correction_counts(self.unit_ids, self.from_date, self.to_date)
        assignment_count, assignment_people = assignment_counts(self.unit_ids, self.from_date, self.to_date)
        stale_master, missing_marks = masterlist_issue_count(self.unit_ids, self.from_date, self.to_date)
        _present_ids, _present_by_unit, unmapped_uid_count, raw_count = raw_presence_sets(
            self.unit_ids,
            *period_bounds_local(self.from_date, self.to_date),
            planned.roster_employee_ids,
        )
        device_summary = device_health_summary(self.unit_ids)

        total_leave = sum(leave_by_date.values())
        leave_denominator = total_planned_person_days + total_leave
        leave_rate = percent_value(total_leave, leave_denominator)
        avg_registered = round(total_planned_person_days / len(self.days), 1) if self.days else 0
        avg_presence_rate = percent_value(total_present_registered, total_planned_person_days)
        compliance_rate = percent_value(committed_unit_days, unit_day_total)

        unit_map = {u.id: u for u in self.units}
        top_leave_units = []
        for uid, count in leave_by_unit.most_common(8):
            unit = unit_map.get(uid)
            top_leave_units.append({"unit": unit_symbol(unit), "unit_label": unit_label(unit), "leave": int(count)})
        top_overtime_units = []
        for uid, value in sorted(overtime_by_unit.items(), key=lambda kv: kv[1], reverse=True)[:8]:
            unit = unit_map.get(uid)
            top_overtime_units.append({"unit": unit_symbol(unit), "unit_label": unit_label(unit), "overtime": float(value)})

        action_items = build_period_action_items(
            self.from_date,
            self.to_date,
            self.selected_unit_id,
            can_view_device_monitor=user_can_view_device_monitor,
            missing_unit_days=missing_unit_days,
            draft_unit_days=draft_unit_days,
            locked_unit_days=locked_unit_days,
            pending_corrections=pending_corrections,
            waiting_apply_corrections=waiting_apply_corrections,
            stale_master=stale_master,
            missing_marks=missing_marks,
            unmapped_uid_count=unmapped_uid_count,
            device_warnings=device_summary["warnings"],
        )

        kpis = [
            {
                "title": "Sĩ số đăng ký bình quân",
                "value": display_number(avg_registered),
                "subtext": "Bình quân người đăng ký làm mỗi ngày",
                "icon": "ti-users-group",
                "class": "primary",
                "url": "#presence-trend-section",
            },
            {
                "title": "Tỷ lệ hiện diện bình quân",
                "value": f"{avg_presence_rate}%" if avg_presence_rate is not None else "—",
                "subtext": presence_source_label,
                "icon": "ti-percentage",
                "class": "success" if avg_presence_rate is not None and avg_presence_rate >= 95 else "warning",
                "url": "#presence-trend-section",
            },
            {
                "title": "Tổng công làm",
                "value": display_number(planned.work_credit_total),
                "subtext": "Tính từ công chốt hoặc nháp tạm tính",
                "icon": "ti-sum",
                "class": "primary",
                "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.from_date.isoformat(), to_date=self.to_date.isoformat(), unit=self.selected_unit_id),
            },
            {
                "title": "Tổng giờ làm thêm",
                "value": display_number(planned.overtime_total),
                "subtext": "Tổng overtime_hours trong kỳ",
                "icon": "ti-clock-plus",
                "class": "info",
                "url": "#top-overtime-section",
            },
            {
                "title": "Tỷ lệ nghỉ trong kỳ",
                "value": f"{leave_rate}%" if leave_rate is not None else "—",
                "subtext": f"{display_number(total_leave)} lượt nghỉ / {display_number(leave_denominator)} lượt công",
                "icon": "ti-bed",
                "class": "warning" if leave_rate and leave_rate > 5 else "success",
                "url": "#leave-trend-section",
            },
            {
                "title": "Hoàn thành chốt công",
                "value": f"{compliance_rate}%" if compliance_rate is not None else "—",
                "subtext": f"{display_number(committed_unit_days)}/{display_number(unit_day_total)} lượt đơn vị/ngày",
                "icon": "ti-checkup-list",
                "class": "success" if compliance_rate is not None and compliance_rate >= 95 else "warning",
                "url": url_with_query("backoffice:attendance_report_dashboard", from_date=self.from_date.isoformat(), to_date=self.to_date.isoformat(), unit=self.selected_unit_id),
            },
        ]

        chart_payload = {
            "mode": "period",
            "presence_trend": trend_presence,
            "leave_trend": trend_leave,
            "top_leave_units": top_leave_units,
            "top_overtime_units": top_overtime_units,
        }

        return {
            "page_title": "Tổng quan hệ thống",
            "mode": "period",
            "filters": self._filters(),
            "kpis": kpis,
            "presence_trend": trend_presence,
            "leave_trend": trend_leave,
            "top_leave_units": top_leave_units,
            "top_overtime_units": top_overtime_units,
            "action_items": action_items,
            "device_summary": device_summary,
            "period_summary": {
                "days": len(self.days),
                "unit_day_total": unit_day_total,
                "committed_unit_days": committed_unit_days,
                "draft_unit_days": draft_unit_days,
                "missing_unit_days": missing_unit_days,
                "assignment_count": assignment_count,
                "assignment_people": assignment_people,
                "raw_count": raw_count,
            },
            "chart_payload": chart_payload,
            "quick_links": quick_links(self.request.user),
        }

    def _filters(self):
        return {
            "mode": "period",
            "work_date": self.to_date,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "group_by": self.group_by,
            "selected_unit_id": self.selected_unit_id or "",
            "units": self.allowed_units,
        }

    def _empty_context(self):
        return {
            "page_title": "Tổng quan hệ thống",
            "mode": "period",
            "filters": self._filters(),
            "kpis": [],
            "presence_trend": [],
            "leave_trend": [],
            "top_leave_units": [],
            "top_overtime_units": [],
            "action_items": [],
            "device_summary": {"total": 0, "online": 0, "warnings": 0, "rows": []},
            "period_summary": {},
            "chart_payload": {"mode": "period", "presence_trend": [], "leave_trend": []},
            "quick_links": [],
        }
