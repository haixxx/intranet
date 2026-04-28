from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls

from django.db import transaction

from apps.attendance.models_batch import AttendanceCommit
from apps.hr.models import Employee

from .models import AttendancePunchMatchV2
from .models_daily_audit import AttendanceDailyDeviceAuditV2


@dataclass
class SnapshotResult:
    work_date: str
    unit_id: int
    commit_id: int
    rows_upserted: int = 0
    notes: str = ""


def _expected_flags_from_commit_item(ci) -> dict:
    code = ci.code
    expected_in1 = bool(code and code.is_work and code.requires_am_work)
    expected_out1 = bool(code and code.is_work and code.requires_am_work)
    expected_in2 = bool(code and code.is_work and code.requires_pm_work)
    expected_out2 = bool(code and code.is_work and code.requires_pm_work)
    expected_marks = int(expected_in1) + int(expected_out1) + int(expected_in2) + int(expected_out2)
    return {
        "expected_in1": expected_in1,
        "expected_out1": expected_out1,
        "expected_in2": expected_in2,
        "expected_out2": expected_out2,
        "expected_marks": expected_marks,
    }


def _minutes(delta_seconds: int | None) -> int | None:
    if delta_seconds is None:
        return None
    # làm tròn về phút gần nhất
    return int(round(delta_seconds / 60))


@transaction.atomic
def build_daily_snapshot_for_unit_date(*, unit_id: int, work_date: date_cls, compute_run_id: str = "") -> SnapshotResult:
    """
    Commit-only snapshot:
    - tìm AttendanceCommit theo unit/date
    - dùng AttendancePunchMatchV2 (run mới nhất hoặc run_id truyền vào)
    - upsert AttendanceDailyDeviceAuditV2
    """
    commit = AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).first()
    if not commit:
        return SnapshotResult(work_date=str(work_date), unit_id=unit_id, commit_id=0, notes="No commit => skip snapshot.")

    items = list(commit.items.select_related("employee", "code").all())
    commit_id = commit.id

    qs = AttendancePunchMatchV2.objects.select_related("employee").filter(
        work_date=work_date,
        employee__unit_id=unit_id,
    )

    # commit-only: prefer compute_run_id nếu truyền, nếu không lấy run mới nhất
    if compute_run_id:
        qs = qs.filter(compute_run_id=compute_run_id)
        run_used = compute_run_id
    else:
        run_used = qs.order_by("-created_at").values_list("compute_run_id", flat=True).first() or ""
        if run_used:
            qs = qs.filter(compute_run_id=run_used)

    matches = list(qs.order_by("employee_id", "target_field"))

    # map (emp_id -> {IN1: match, ...})
    m_map: dict[int, dict[str, AttendancePunchMatchV2]] = {}
    for m in matches:
        m_map.setdefault(m.employee_id, {})[m.target_field] = m

    # upsert: xóa rows cũ của unit/date trước (an toàn)
    AttendanceDailyDeviceAuditV2.objects.filter(work_date=work_date, unit_id=unit_id).delete()

    created = 0
    for ci in items:
        if hasattr(ci, "include_in_unit") and not bool(ci.include_in_unit):
            continue

        emp: Employee = ci.employee
        is_exempt = bool(getattr(emp, "skip_device_attendance", False))

        exp = _expected_flags_from_commit_item(ci)
        expected_marks = exp["expected_marks"]

        # nếu expected_marks = 0 => không audit ngày đó (nghỉ/không đi làm)
        if expected_marks == 0:
            continue

        mm = m_map.get(emp.id, {})

        def is_missing(field: str) -> bool:
            if field not in mm:
                # nếu không có record match thì coi như missing (vì expected có)
                return True
            return mm[field].status == AttendancePunchMatchV2.Status.MISSING

        # missing flags chỉ tính nếu NOT exempt
        missing_in1 = (not is_exempt) and exp["expected_in1"] and is_missing("IN1")
        missing_out1 = (not is_exempt) and exp["expected_out1"] and is_missing("OUT1")
        missing_in2 = (not is_exempt) and exp["expected_in2"] and is_missing("IN2")
        missing_out2 = (not is_exempt) and exp["expected_out2"] and is_missing("OUT2")

        missing_marks = int(missing_in1) + int(missing_out1) + int(missing_in2) + int(missing_out2)
        matched_marks = 0 if is_exempt else (expected_marks - missing_marks)

        def delta_minutes(field: str) -> int | None:
            m = mm.get(field)
            if not m or m.status != AttendancePunchMatchV2.Status.MATCHED:
                return None
            return _minutes(m.delta_seconds)

        AttendanceDailyDeviceAuditV2.objects.create(
            work_date=work_date,
            unit_id=unit_id,
            commit_id=commit_id,
            employee=emp,
            is_exempt=is_exempt,
            expected_in1=exp["expected_in1"],
            expected_out1=exp["expected_out1"],
            expected_in2=exp["expected_in2"],
            expected_out2=exp["expected_out2"],
            expected_marks=expected_marks,
            missing_in1=missing_in1,
            missing_out1=missing_out1,
            missing_in2=missing_in2,
            missing_out2=missing_out2,
            matched_marks=matched_marks,
            missing_marks=0 if is_exempt else missing_marks,
            delta_in1_minutes=delta_minutes("IN1"),
            delta_out1_minutes=delta_minutes("OUT1"),
            delta_in2_minutes=delta_minutes("IN2"),
            delta_out2_minutes=delta_minutes("OUT2"),
            compute_run_id=run_used,
            compute_version=1,
        )
        created += 1

    return SnapshotResult(work_date=str(work_date), unit_id=unit_id, commit_id=commit_id, rows_upserted=created, notes=f"run_id={run_used}")