from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q

from apps.attendance.models import AttendanceCode
from apps.attendance.models_batch import (
    AttendanceBatch,
    AttendanceBatchItem,
    AttendanceCommit,
    AttendanceCommitItem,
    AttendanceCorrectionRequest,
)
from apps.hr.models import TempAssignment

from .common import decimal_value


PENDING_CORRECTION_STATUSES = [
    AttendanceCorrectionRequest.Status.REQUESTED,
    AttendanceCorrectionRequest.Status.APPROVED_BY_UNIT,
]
WAITING_APPLY_CORRECTION_STATUSES = [AttendanceCorrectionRequest.Status.APPROVED_BY_HR]
OPEN_CORRECTION_STATUSES = PENDING_CORRECTION_STATUSES + WAITING_APPLY_CORRECTION_STATUSES
EFFECTIVE_ASSIGNMENT_STATUSES = TempAssignment.effective_statuses()


def commit_item_is_work(item: AttendanceCommitItem) -> bool:
    if getattr(item, "code_snapshot", ""):
        return bool(getattr(item, "is_work_snapshot", False))
    code = getattr(item, "code", None)
    return bool(getattr(code, "is_work", False))


def batch_item_is_work(item: AttendanceBatchItem) -> bool:
    code = getattr(item, "code", None)
    return bool(getattr(code, "is_work", False))


def commit_item_work_credit(item: AttendanceCommitItem) -> Decimal:
    if getattr(item, "code_snapshot", ""):
        return decimal_value(getattr(item, "work_credit_snapshot", 0))
    code = getattr(item, "code", None)
    return decimal_value(getattr(code, "work_credit", 0) if code else 0)


def batch_item_work_credit(item: AttendanceBatchItem) -> Decimal:
    code = getattr(item, "code", None)
    return decimal_value(getattr(code, "work_credit", 0) if code else 0)


def item_include_in_unit(item) -> bool:
    return bool(getattr(item, "include_in_unit", True))


def get_source_items(unit_ids: list[int], from_date, to_date):
    """
    Trả về items đã chốt hoặc nháp theo quy tắc:
    - Có AttendanceCommit: dùng commit item.
    - Chưa commit nhưng có AttendanceBatch DRAFT: dùng batch item.
    - LOCKED_DRAFT không commit được trả ra ở locked_keys để cảnh báo.
    """
    commits = list(
        AttendanceCommit.objects.filter(unit_id__in=unit_ids, work_date__gte=from_date, work_date__lte=to_date)
        .select_related("unit")
    )
    commit_keys = {(c.unit_id, c.work_date) for c in commits}
    commit_ids = [c.id for c in commits]

    draft_batches = list(
        AttendanceBatch.objects.filter(
            unit_id__in=unit_ids,
            work_date__gte=from_date,
            work_date__lte=to_date,
            status=AttendanceBatch.Status.DRAFT,
        ).select_related("unit")
    )
    draft_batches = [b for b in draft_batches if (b.unit_id, b.work_date) not in commit_keys]
    batch_keys = {(b.unit_id, b.work_date) for b in draft_batches}
    batch_ids = [b.id for b in draft_batches]

    locked_keys = set(
        AttendanceBatch.objects.filter(
            unit_id__in=unit_ids,
            work_date__gte=from_date,
            work_date__lte=to_date,
            status=AttendanceBatch.Status.LOCKED_DRAFT,
        ).values_list("unit_id", "work_date")
    )
    locked_keys = {key for key in locked_keys if key not in commit_keys}

    commit_items = []
    if commit_ids:
        commit_items = list(
            AttendanceCommitItem.objects.filter(commit_id__in=commit_ids)
            .select_related("commit", "commit__unit", "employee", "employee__unit", "employee__team", "code")
        )
    batch_items = []
    if batch_ids:
        batch_items = list(
            AttendanceBatchItem.objects.filter(batch_id__in=batch_ids)
            .select_related("batch", "batch__unit", "employee", "employee__unit", "employee__team", "code")
        )
    return commit_items, batch_items, commit_keys, batch_keys, locked_keys


@dataclass
class PlannedData:
    work_employee_ids: set[int]
    leave_employee_ids: set[int]
    roster_employee_ids: set[int]
    work_by_unit: dict[int, set[int]]
    leave_by_unit: dict[int, int]
    roster_by_unit: dict[int, int]
    work_credit_by_unit: dict[int, Decimal]
    overtime_by_unit: dict[int, Decimal]
    work_credit_total: Decimal
    overtime_total: Decimal


def build_planned_data(commit_items, batch_items) -> PlannedData:
    work_employee_ids: set[int] = set()
    leave_employee_ids: set[int] = set()
    roster_employee_ids: set[int] = set()
    work_by_unit: dict[int, set[int]] = defaultdict(set)
    leave_by_unit: dict[int, int] = Counter()
    roster_by_unit: dict[int, int] = Counter()
    work_credit_by_unit: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    overtime_by_unit: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    work_credit_total = Decimal("0.00")
    overtime_total = Decimal("0.00")

    for item in commit_items:
        if not item_include_in_unit(item):
            continue
        unit_id = item.commit.unit_id
        emp_id = item.employee_id
        roster_employee_ids.add(emp_id)
        roster_by_unit[unit_id] += 1
        is_work = commit_item_is_work(item)
        if is_work:
            work_employee_ids.add(emp_id)
            work_by_unit[unit_id].add(emp_id)
            credit = commit_item_work_credit(item)
            work_credit_by_unit[unit_id] += credit
            work_credit_total += credit
            ot = decimal_value(getattr(item, "overtime_hours", 0))
            overtime_by_unit[unit_id] += ot
            overtime_total += ot
        else:
            leave_employee_ids.add(emp_id)
            leave_by_unit[unit_id] += 1

    for item in batch_items:
        if not item_include_in_unit(item):
            continue
        unit_id = item.batch.unit_id
        emp_id = item.employee_id
        roster_employee_ids.add(emp_id)
        roster_by_unit[unit_id] += 1
        is_work = batch_item_is_work(item)
        if is_work:
            work_employee_ids.add(emp_id)
            work_by_unit[unit_id].add(emp_id)
            credit = batch_item_work_credit(item)
            work_credit_by_unit[unit_id] += credit
            work_credit_total += credit
            ot = decimal_value(getattr(item, "overtime_hours", 0))
            overtime_by_unit[unit_id] += ot
            overtime_total += ot
        else:
            leave_employee_ids.add(emp_id)
            leave_by_unit[unit_id] += 1

    return PlannedData(
        work_employee_ids=work_employee_ids,
        leave_employee_ids=leave_employee_ids,
        roster_employee_ids=roster_employee_ids,
        work_by_unit=work_by_unit,
        leave_by_unit=leave_by_unit,
        roster_by_unit=roster_by_unit,
        work_credit_by_unit=work_credit_by_unit,
        overtime_by_unit=overtime_by_unit,
        work_credit_total=work_credit_total,
        overtime_total=overtime_total,
    )


def correction_counts(unit_ids: list[int], from_date, to_date):
    qs = AttendanceCorrectionRequest.objects.filter(unit_id__in=unit_ids, work_date__gte=from_date, work_date__lte=to_date)
    pending = qs.filter(status__in=PENDING_CORRECTION_STATUSES).count()
    waiting_apply = qs.filter(status__in=WAITING_APPLY_CORRECTION_STATUSES).count()
    return pending, waiting_apply


def committed_role_people_counts(unit_ids: list[int], from_date, to_date) -> dict[str, int]:
    """
    Đếm số người theo nhóm mã công từ dữ liệu đã chốt.

    Dashboard tổng quan chỉ dùng dữ liệu công chốt cho các ô Công tác/Nghỉ ốm/Nghỉ phép
    để tránh nhầm với nháp hoặc dữ liệu chưa hoàn tất. Đếm distinct employee_id vì đây là
    chỉ số "số người", không phải số dòng công.
    """
    qs = AttendanceCommitItem.objects.filter(
        commit__unit_id__in=unit_ids,
        commit__work_date__gte=from_date,
        commit__work_date__lte=to_date,
        include_in_unit=True,
    ).select_related("commit", "code")

    result = {
        "business_trip": set(),
        "sick_leave": set(),
        "paid_leave": set(),
    }

    for item in qs:
        role = (getattr(item, "system_role_snapshot", "") or "").strip()
        if not role and item.code_id and item.code:
            role = getattr(item.code, "system_role", "") or ""

        if role == AttendanceCode.SystemRole.BUSINESS_TRIP:
            result["business_trip"].add(item.employee_id)
        elif role in {AttendanceCode.SystemRole.SICK_LEAVE, AttendanceCode.SystemRole.CHILD_SICK}:
            result["sick_leave"].add(item.employee_id)
        elif role == AttendanceCode.SystemRole.PAID_LEAVE:
            result["paid_leave"].add(item.employee_id)

    return {key: len(value) for key, value in result.items()}


def assignment_counts(unit_ids: list[int], from_date, to_date):
    qs = TempAssignment.objects.filter(
        status__in=EFFECTIVE_ASSIGNMENT_STATUSES,
        start_date__lte=to_date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=from_date))
    qs = qs.filter(Q(from_unit_id__in=unit_ids) | Q(to_unit_id__in=unit_ids))
    people = qs.values_list("employee_id", flat=True).distinct().count()
    return qs.count(), people
