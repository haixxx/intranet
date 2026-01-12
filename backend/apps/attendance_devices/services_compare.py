from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional, List, Dict

from django.db.models import Q

from apps.hr.models import Employee
from apps.organization.models import OrgUnit
from apps.attendance.models import AttendanceCode
from apps.attendance.models_batch import AttendanceCommit, AttendanceCommitItem
from .models import AttendanceDayFacts


@dataclass
class CompareRow:
    employee_id: int
    employee_code: str
    employee_name: str
    team_name: str | None
    work_date: date

    # committed (đã chốt)
    code: str
    requires_am: bool
    requires_pm: bool
    committed_in1: Optional[time]
    committed_out1: Optional[time]
    committed_in2: Optional[time]
    committed_out2: Optional[time]

    # machine effective (máy sau overlay)
    eff_in1: Optional[time]
    eff_out1: Optional[time]
    eff_in2: Optional[time]
    eff_out2: Optional[time]

    # diff minutes (dương = đi muộn/ra sớm; 0 nếu không tính)
    am_late_min: int
    am_early_min: int
    pm_late_min: int
    pm_early_min: int

    # missing flags (thiếu mốc yêu cầu)
    missing_am_in_out: bool
    missing_pm_in_out: bool


def _diff_minutes(committed: Optional[time], effective: Optional[time], invert=False) -> int:
    """
    Trả về số phút chênh lệch dương theo nghĩa:
    - invert=False: late = effective - committed (dương nếu đến muộn)
    - invert=True: early = committed - effective (dương nếu ra sớm)
    Nếu thiếu một trong hai -> 0 (không tính).
    """
    if not committed or not effective:
        return 0
    cd = datetime(2000, 1, 1, committed.hour, committed.minute, committed.second)
    ed = datetime(2000, 1, 1, effective.hour, effective.minute, effective.second)
    delta = (ed - cd) if not invert else (cd - ed)
    minutes = int(delta.total_seconds() // 60)
    return minutes if minutes > 0 else 0


def compare_day_vs_committed(work_date: date, unit: OrgUnit,
                             team_id: Optional[int] = None,
                             q: str = "") -> List[CompareRow]:
    """
    So sánh AttendanceDayFacts.effective_* với AttendanceCommitItem của ngày/đơn vị (chỉ include_in_unit=True).
    - Lọc nhân sự theo unit + team (nếu có).
    - Nếu không có commit cho ngày/đơn vị này, view sẽ báo thông báo ở ngoài (rows trả về rỗng).
    """
    commit = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
    if not commit:
        return []

    # Lấy items đã chốt trong đơn vị/ngày (chỉ include_in_unit=True)
    ci_qs = commit.items.select_related("employee", "code").filter(include_in_unit=True)
    if q:
        ci_qs = ci_qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
    if team_id:
        ci_qs = ci_qs.filter(employee__team_id=team_id)

    emp_ids = list(ci_qs.values_list("employee_id", flat=True))

    # Map DayFacts cho các nhân sự đã chốt
    facts_map: Dict[int, AttendanceDayFacts | None] = {
        df.employee_id: df
        for df in AttendanceDayFacts.objects.filter(work_date=work_date, employee_id__in=emp_ids)
    }

    rows: List[CompareRow] = []
    for ci in ci_qs:
        emp = ci.employee
        code_obj = ci.code
        code = code_obj.code if code_obj else "NONE"

        requires_am = False
        requires_pm = False
        if code_obj:
            requires_am = (code_obj.segments_am_type == AttendanceCode.SegmentType.WORK) and code_obj.requires_am_work
            requires_pm = (code_obj.segments_pm_type == AttendanceCode.SegmentType.WORK) and code_obj.requires_pm_work

        df = facts_map.get(emp.id)
        eff_in1 = getattr(df, "effective_in1", None) if df else None
        eff_out1 = getattr(df, "effective_out1", None) if df else None
        eff_in2 = getattr(df, "effective_in2", None) if df else None
        eff_out2 = getattr(df, "effective_out2", None) if df else None

        committed_in1 = ci.in1
        committed_out1 = ci.out1
        committed_in2 = ci.in2
        committed_out2 = ci.out2

        am_late = _diff_minutes(committed_in1, eff_in1, invert=False) if requires_am else 0
        am_early = _diff_minutes(committed_out1, eff_out1, invert=True) if requires_am else 0
        pm_late = _diff_minutes(committed_in2, eff_in2, invert=False) if requires_pm else 0
        pm_early = _diff_minutes(committed_out2, eff_out2, invert=True) if requires_pm else 0

        missing_am = requires_am and (not committed_in1 or not committed_out1 or not eff_in1 or not eff_out1)
        missing_pm = requires_pm and (not committed_in2 or not committed_out2 or not eff_in2 or not eff_out2)

        rows.append(CompareRow(
            employee_id=emp.id,
            employee_code=emp.employee_code,
            employee_name=emp.full_name,
            team_name=getattr(emp.team, "name", None),
            work_date=work_date,
            code=code,
            requires_am=requires_am,
            requires_pm=requires_pm,
            committed_in1=committed_in1,
            committed_out1=committed_out1,
            committed_in2=committed_in2,
            committed_out2=committed_out2,
            eff_in1=eff_in1,
            eff_out1=eff_out1,
            eff_in2=eff_in2,
            eff_out2=eff_out2,
            am_late_min=am_late,
            am_early_min=am_early,
            pm_late_min=pm_late,
            pm_early_min=pm_early,
            missing_am_in_out=missing_am,
            missing_pm_in_out=missing_pm,
        ))

    return rows


def apply_filters_and_sort(rows: List[CompareRow],
                           only_late: bool = False,
                           only_early: bool = False,
                           only_missing: bool = False,
                           threshold_min: int = 0,
                           sort_by: str = "severity_desc") -> List[CompareRow]:
    """
    Lọc và sắp xếp:
    - only_late: chỉ hiển thị có đi muộn (AM hoặc PM) vượt ngưỡng.
    - only_early: chỉ hiển thị có ra sớm (AM hoặc PM) vượt ngưỡng.
    - only_missing: chỉ hiển thị thiếu mốc yêu cầu (AM hoặc PM).
    - threshold_min: ngưỡng phút (ví dụ 5 hoặc 10).
    - sort_by:
      - severity_desc: tổng phút muộn+sớm (AM+PM) giảm dần
      - am_late_desc, am_early_desc, pm_late_desc, pm_early_desc
      - name_asc, team_asc, code_asc
    """
    def passes(r: CompareRow) -> bool:
        late_ok = (r.am_late_min >= threshold_min) or (r.pm_late_min >= threshold_min)
        early_ok = (r.am_early_min >= threshold_min) or (r.pm_early_min >= threshold_min)
        missing_ok = r.missing_am_in_out or r.missing_pm_in_out

        if only_missing:
            return missing_ok
        if only_late and only_early:
            return late_ok and early_ok
        if only_late:
            return late_ok
        if only_early:
            return early_ok
        if threshold_min > 0:
            return late_ok or early_ok or missing_ok
        return True

    filtered = [r for r in rows if passes(r)]

    def severity(r: CompareRow) -> int:
        return (r.am_late_min + r.pm_late_min + r.am_early_min + r.pm_early_min)

    if sort_by == "severity_desc":
        filtered.sort(key=severity, reverse=True)
    elif sort_by == "am_late_desc":
        filtered.sort(key=lambda r: r.am_late_min, reverse=True)
    elif sort_by == "am_early_desc":
        filtered.sort(key=lambda r: r.am_early_min, reverse=True)
    elif sort_by == "pm_late_desc":
        filtered.sort(key=lambda r: r.pm_late_min, reverse=True)
    elif sort_by == "pm_early_desc":
        filtered.sort(key=lambda r: r.pm_early_min, reverse=True)
    elif sort_by == "name_asc":
        filtered.sort(key=lambda r: (r.employee_name or "").lower())
    elif sort_by == "team_asc":
        filtered.sort(key=lambda r: (r.team_name or "").lower())
    elif sort_by == "code_asc":
        filtered.sort(key=lambda r: (r.code or "").lower())

    return filtered