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


def _iter_targets_from_code_and_item(code: AttendanceCode, item) -> list[tuple[str, dt_time]]:
    targets: list[tuple[str, dt_time]] = []

    if not code or not code.is_work:
        return targets

    # AM
    if code.requires_am_work:
        if item.in1:
            targets.append(("IN1", item.in1))
        if item.out1:
            targets.append(("OUT1", item.out1))

    # PM
    if code.requires_pm_work:
        if item.in2:
            targets.append(("IN2", item.in2))
        if item.out2:
            targets.append(("OUT2", item.out2))

    return targets


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
    day_end_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(23, 59, 59)), tz) + window
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
        targets = _iter_targets_from_code_and_item(code, it)
        if not targets:
            continue

        if bool(getattr(emp, "skip_device_attendance", False)):
            for field, tval in targets:
                target_local = _make_local_dt(work_date, tval)
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

        for field, tval in targets:
            target_local = _make_local_dt(work_date, tval)
            m = _pick_nearest_punch(target_local=target_local, punches=punches, window=window, used_ids=used)
            if m:
                used.add(m.id)
                create_match(emp=emp, field=field, target_local=target_local, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
            else:
                create_match(emp=emp, field=field, target_local=target_local, matched=None, status=AttendancePunchMatchV2.Status.MISSING)

    return res