from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time, timezone as datetime_timezone
from typing import Literal

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.attendance.models import AttendanceSettings, AttendanceCode
from apps.attendance.models_batch import AttendanceCommit
from apps.hr.models import Employee

from .models import AttendanceNormalizedPunchV2, AttendancePunchMatchV2


SourceMode = Literal["commit"]

OVERNIGHT_END_CUTOFF = dt_time(8, 0)


@dataclass
class ComputeAuditResult:
    work_date: str
    unit_id: int
    source_used: str
    employees_scanned: int = 0
    matches_created: int = 0
    exempt_rows: int = 0
    notes: str = ""


def _get_window_minutes() -> int:
    s = AttendanceSettings.objects.first()
    if s and s.window_minutes:
        return int(s.window_minutes)
    return 60


def _make_local_dt(work_date, t: dt_time) -> datetime:
    tz = dj_timezone.get_current_timezone()
    naive = datetime.combine(work_date, t)
    return dj_timezone.make_aware(naive, tz)


def _make_target_dt(work_date, t: dt_time | None, *, next_day: bool = False) -> datetime | None:
    if not t:
        return None
    target_date = work_date + timedelta(days=1) if next_day else work_date
    return _make_local_dt(target_date, t)


def _pair_targets(work_date, in_time: dt_time | None, out_time: dt_time | None, in_field: str, out_field: str):
    """
    Tạo target cho một cặp vào/ra. Nếu giờ ra <= giờ vào thì hiểu giờ ra là ngày hôm sau.
    Quy tắc này xử lý đúng L3 dạng 22:00-06:00 ở mốc 1, không chỉ riêng OUT2.
    """
    out_next_day = bool(in_time and out_time and out_time <= in_time)
    return [
        (in_field, _make_target_dt(work_date, in_time)),
        (out_field, _make_target_dt(work_date, out_time, next_day=out_next_day)),
    ]


def _pick_nearest_punch(
    *,
    target_local: datetime,
    punches: list[AttendanceNormalizedPunchV2],
    window: timedelta,
    used_ids: set[int],
) -> AttendanceNormalizedPunchV2 | None:
    target_utc = target_local.astimezone(datetime_timezone.utc)

    best = None
    best_abs = None
    for p in punches:
        if p.id in used_ids:
            continue
        delta = p.canonical_time_utc - target_utc
        abs_sec = abs(int(delta.total_seconds()))
        if abs_sec <= int(window.total_seconds()):
            if best is None or abs_sec < best_abs:
                best = p
                best_abs = abs_sec
    return best


def _iter_targets_from_code_and_item(code: AttendanceCode, item, work_date) -> tuple[list[tuple[str, datetime]], list[str]]:
    targets: list[tuple[str, datetime]] = []
    missing_required: list[str] = []

    # Sau Phase 5C, thiết bị v2 ưu tiên snapshot của công chốt:
    # - is_work_snapshot cho biết dòng có đi làm theo thời điểm chốt;
    # - registered_*_snapshot là mốc đăng ký đã chốt, lấy từ BatchItem khi bấm Chốt công.
    # Với dữ liệu cũ chưa có snapshot, fallback về code.requires_* + item.in/out như trước.
    has_snapshot = bool(getattr(item, "code_snapshot", ""))
    is_work = bool(getattr(item, "is_work_snapshot", False)) if has_snapshot else bool(code and code.is_work)
    if not is_work:
        return targets, missing_required

    if has_snapshot:
        in1 = getattr(item, "registered_in1_snapshot", None)
        out1 = getattr(item, "registered_out1_snapshot", None)
        in2 = getattr(item, "registered_in2_snapshot", None)
        out2 = getattr(item, "registered_out2_snapshot", None)
        for field, target_dt in _pair_targets(work_date, in1, out1, "IN1", "OUT1") + _pair_targets(work_date, in2, out2, "IN2", "OUT2"):
            if target_dt:
                targets.append((field, target_dt))
        return targets, missing_required

    if not code:
        return targets, missing_required

    expected_fields: list[tuple[str, dt_time | None]] = []
    if code.requires_am_work:
        expected_fields.extend([
            ("IN1", getattr(item, "in1", None)),
            ("OUT1", getattr(item, "out1", None)),
        ])
    if code.requires_pm_work:
        expected_fields.extend([
            ("IN2", getattr(item, "in2", None)),
            ("OUT2", getattr(item, "out2", None)),
        ])

    expected_time_map = {field: t for field, t in expected_fields}
    target_map = dict(_pair_targets(work_date, expected_time_map.get("IN1"), expected_time_map.get("OUT1"), "IN1", "OUT1"))
    target_map.update(dict(_pair_targets(work_date, expected_time_map.get("IN2"), expected_time_map.get("OUT2"), "IN2", "OUT2")))
    for field, t in expected_fields:
        target_dt = target_map.get(field)
        if target_dt:
            targets.append((field, target_dt))
        else:
            missing_required.append(field)

    return targets, missing_required

@transaction.atomic
def compute_audit_for_unit_date(
    *,
    unit_id: int,
    work_date,
    source: SourceMode = "commit",
    compute_run_id: str = "",
    compute_version: int = 1,
) -> ComputeAuditResult:
    """
    Commit-only (phương án A):
    - Chỉ compute nếu có AttendanceCommit cho unit/date.
    - Output: AttendancePunchMatchV2
    """
    window = timedelta(minutes=_get_window_minutes())

    commit = AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).first()
    if not commit:
        return ComputeAuditResult(
            work_date=str(work_date),
            unit_id=unit_id,
            source_used="commit",
            notes="Không có AttendanceCommit cho unit/date này => không compute (commit-only).",
        )

    items = list(commit.items.select_related("employee", "code").all())
    res = ComputeAuditResult(
        work_date=str(work_date),
        unit_id=unit_id,
        source_used="commit",
        employees_scanned=len(items),
        notes=f"commit_id={commit.id}",
    )

    if compute_run_id:
        AttendancePunchMatchV2.objects.filter(work_date=work_date, compute_run_id=compute_run_id).delete()

    tz = dj_timezone.get_current_timezone()
    day_start_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(0, 0, 0)), tz) - window
    day_end_local = dj_timezone.make_aware(datetime.combine(work_date + timedelta(days=1), OVERNIGHT_END_CUTOFF), tz) + window
    start_utc = day_start_local.astimezone(datetime_timezone.utc)
    end_utc = day_end_local.astimezone(datetime_timezone.utc)

    emp_ids = [it.employee_id for it in items]
    punches_qs = (
        AttendanceNormalizedPunchV2.objects
        .filter(employee_id__in=emp_ids, canonical_time_utc__gte=start_utc, canonical_time_utc__lte=end_utc)
        .select_related("best_device")
        .order_by("employee_id", "canonical_time_utc")
    )
    punches_by_emp: dict[int, list[AttendanceNormalizedPunchV2]] = {}
    for p in punches_qs:
        punches_by_emp.setdefault(p.employee_id, []).append(p)

    now = dj_timezone.now()
    missing_target_warnings: list[str] = []

    def create_match(*, emp: Employee, field: str, target_local: datetime, matched: AttendanceNormalizedPunchV2 | None, status: str, notes: str = ""):
        nonlocal res
        if matched:
            matched_local = matched.canonical_time_utc.astimezone(tz)
            delta_seconds = int((matched_local - target_local).total_seconds())
        else:
            matched_local = None
            delta_seconds = None

        AttendancePunchMatchV2.objects.create(
            work_date=work_date,
            employee=emp,
            target_field=field,
            target_time_local=target_local,
            matched_punch=matched,
            matched_time_local=matched_local,
            delta_seconds=delta_seconds,
            status=status,
            notes=notes,
            compute_run_id=compute_run_id,
            compute_version=compute_version,
            created_at=now,
        )
        res.matches_created += 1

    for it in items:
        if hasattr(it, "include_in_unit") and not bool(it.include_in_unit):
            continue

        emp: Employee = it.employee
        code: AttendanceCode = it.code
        targets, missing_required = _iter_targets_from_code_and_item(code, it, work_date)
        if missing_required:
            emp_code = getattr(emp, "employee_code", "") or str(emp.id)
            missing_target_warnings.append(f"{emp_code}: thiếu {','.join(missing_required)}")
        if not targets:
            continue

        if bool(getattr(emp, "skip_device_attendance", False)):
            for field, target_local in targets:
                create_match(
                    emp=emp,
                    field=field,
                    target_local=target_local,
                    matched=None,
                    status=AttendancePunchMatchV2.Status.EXEMPT,
                    notes="Employee được đặc cách, không yêu cầu chấm máy.",
                )
                res.exempt_rows += 1
            continue

        punches = punches_by_emp.get(emp.id, [])
        used: set[int] = set()

        for field, target_local in targets:
            m = _pick_nearest_punch(target_local=target_local, punches=punches, window=window, used_ids=used)
            if m:
                used.add(m.id)
                create_match(emp=emp, field=field, target_local=target_local, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
            else:
                create_match(emp=emp, field=field, target_local=target_local, matched=None, status=AttendancePunchMatchV2.Status.MISSING)

    if missing_target_warnings:
        sample = "; ".join(missing_target_warnings[:20])
        if len(missing_target_warnings) > 20:
            sample += f"; ... còn {len(missing_target_warnings) - 20} dòng"
        res.notes = (res.notes + " | " if res.notes else "") + "mốc công chốt bị thiếu giờ target: " + sample

    return res