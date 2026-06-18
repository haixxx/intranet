from __future__ import annotations

from dataclasses import dataclass
from datetime import date as dt_date
import hashlib
from typing import Dict, List, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.organization.models import OrgUnit
from apps.hr.models import Employee

try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None

from apps.attendance.models_batch import AttendanceBatch, AttendanceBatchItem, AttendanceCommit


try:
    from apps.notifications.models import Notification
except Exception:
    Notification = None


@dataclass(frozen=True)
class RosterEntry:
    employee_id: int
    include_in_unit: bool
    bs_direction: str
    bs_peer_unit_id: Optional[int]


def _effective_temp_assignment_qs(work_date: dt_date):
    if TempAssignment is None:
        return None
    return (
        TempAssignment.objects.filter(
            apply_flag=True,
            status__in=TempAssignment.effective_statuses(),
            start_date__lte=work_date,
        )
        .filter(Q(end_date__gte=work_date) | Q(end_date__isnull=True))
    )


def _active_bs_in_ids(unit: OrgUnit, work_date: dt_date) -> List[int]:
    qs = _effective_temp_assignment_qs(work_date)
    if qs is None:
        return []
    return list(qs.filter(to_unit=unit).values_list("employee_id", flat=True))


def _active_bs_out_ids(unit: OrgUnit, work_date: dt_date) -> List[int]:
    qs = _effective_temp_assignment_qs(work_date)
    if qs is None:
        return []
    return list(qs.filter(from_unit=unit).values_list("employee_id", flat=True))


def build_expected_roster(unit: OrgUnit, work_date: dt_date, team_id: Optional[int] = None) -> List[RosterEntry]:
    """
    Tổ hợp roster kỳ vọng cho đơn vị/ngày dựa vào:
    - Nhân sự ACTIVE thuộc đơn vị gốc.
    - Điều động IN vào đơn vị.
    - Điều động OUT khỏi đơn vị.

    Trạng thái điều động có hiệu lực lịch sử:
    ACTIVE / COMPLETED / EXPIRED.
    CANCELLED không tính.
    """
    base_qs = Employee.objects.filter(unit=unit, status=Employee.Status.ACTIVE)
    if team_id:
        base_qs = base_qs.filter(team_id=team_id)
    base_ids = set(base_qs.values_list("id", flat=True))

    bs_in_ids = set(_active_bs_in_ids(unit, work_date))
    bs_out_ids = set(_active_bs_out_ids(unit, work_date))

    # Nếu sau này build roster theo tổ, BS đi vẫn có thể lọc theo tổ gốc của nhân sự.
    # BS đến chưa có trường "tổ tiếp nhận" tại đơn vị nhận nên vẫn giữ khi lập toàn đơn vị.
    if team_id:
        bs_out_ids = set(Employee.objects.filter(id__in=bs_out_ids, team_id=team_id).values_list("id", flat=True))

    all_ids = base_ids.union(bs_in_ids).union(bs_out_ids)

    peer_unit_map: Dict[int, Optional[int]] = {}
    if TempAssignment is not None:
        ta_qs = _effective_temp_assignment_qs(work_date)
        if ta_qs is not None:
            for ta in ta_qs.select_related("from_unit", "to_unit", "employee"):
                if ta.to_unit_id == unit.id:
                    peer_unit_map[ta.employee_id] = ta.from_unit_id
                elif ta.from_unit_id == unit.id:
                    peer_unit_map[ta.employee_id] = ta.to_unit_id

    roster: List[RosterEntry] = []
    for emp_id in sorted(all_ids):
        in_in = emp_id in bs_in_ids
        in_out = emp_id in bs_out_ids

        if in_out and not in_in:
            roster.append(
                RosterEntry(
                    employee_id=emp_id,
                    include_in_unit=False,
                    bs_direction=AttendanceBatchItem.BSDirection.OUT,
                    bs_peer_unit_id=peer_unit_map.get(emp_id),
                )
            )
        elif in_in and not in_out:
            roster.append(
                RosterEntry(
                    employee_id=emp_id,
                    include_in_unit=True,
                    bs_direction=AttendanceBatchItem.BSDirection.IN,
                    bs_peer_unit_id=peer_unit_map.get(emp_id),
                )
            )
        else:
            roster.append(
                RosterEntry(
                    employee_id=emp_id,
                    include_in_unit=True,
                    bs_direction=AttendanceBatchItem.BSDirection.NONE,
                    bs_peer_unit_id=peer_unit_map.get(emp_id),
                )
            )

    return roster


def compute_roster_signature(entries: List[RosterEntry]) -> str:
    key_parts = [
        f"{e.employee_id}:{int(e.include_in_unit)}:{e.bs_direction}:{e.bs_peer_unit_id or ''}"
        for e in entries
    ]
    joined = "|".join(key_parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def batch_roster_signature(batch: AttendanceBatch) -> str:
    items = list(
        batch.items.values(
            "employee_id",
            "include_in_unit",
            "bs_direction",
            "bs_peer_unit_id",
        ).order_by("employee_id")
    )
    entries = [
        RosterEntry(
            employee_id=it["employee_id"],
            include_in_unit=bool(it["include_in_unit"]),
            bs_direction=it["bs_direction"],
            bs_peer_unit_id=it["bs_peer_unit_id"],
        )
        for it in items
    ]
    return compute_roster_signature(entries)


def compute_roster_diff(batch: AttendanceBatch, expected: List[RosterEntry]) -> Dict[str, List[Dict]]:
    exp_map: Dict[int, RosterEntry] = {e.employee_id: e for e in expected}
    batch_map: Dict[int, AttendanceBatchItem] = {it.employee_id: it for it in batch.items.all()}

    add, remove, update = [], [], []

    for emp_id, e in exp_map.items():
        it = batch_map.get(emp_id)
        if not it:
            add.append(
                {
                    "employee_id": emp_id,
                    "include_in_unit": e.include_in_unit,
                    "bs_direction": e.bs_direction,
                    "bs_peer_unit_id": e.bs_peer_unit_id,
                }
            )
        else:
            need_update = (
                bool(it.include_in_unit) != bool(e.include_in_unit)
                or str(it.bs_direction) != str(e.bs_direction)
                or (it.bs_peer_unit_id or None) != (e.bs_peer_unit_id or None)
            )
            if need_update:
                update.append(
                    {
                        "employee_id": emp_id,
                        "old": {
                            "include_in_unit": bool(it.include_in_unit),
                            "bs_direction": str(it.bs_direction),
                            "bs_peer_unit_id": it.bs_peer_unit_id,
                        },
                        "new": {
                            "include_in_unit": bool(e.include_in_unit),
                            "bs_direction": str(e.bs_direction),
                            "bs_peer_unit_id": e.bs_peer_unit_id,
                        },
                    }
                )

    for emp_id, it in batch_map.items():
        if emp_id not in exp_map:
            if bool(it.include_in_unit):
                remove.append(
                    {
                        "employee_id": emp_id,
                        "include_in_unit": bool(it.include_in_unit),
                        "bs_direction": str(it.bs_direction),
                        "bs_peer_unit_id": it.bs_peer_unit_id,
                    }
                )

    return {"add": add, "remove": remove, "update": update}


@transaction.atomic
def apply_roster_diff(batch: AttendanceBatch, diff: Dict[str, List[Dict]]) -> Dict[str, int]:
    """
    Áp dụng thay đổi danh sách chấm công vào batch nháp theo cách an toàn.

    Nguyên tắc:
    - Không xóa toàn bộ batch.
    - Giữ nguyên code, IN/OUT, ghi chú của dòng không bị ảnh hưởng.
    - Người mới thêm: IN/NONE mặc định LL; OUT mặc định BS nếu có.
    - Khi một dòng chuyển sang BS đi/OUT: ép mã BS nếu có và xóa toàn bộ mốc giờ.
    - Khi một dòng từ OUT quay lại IN/NONE: nếu đang là mã BS thì chuyển về LL và lấy giờ mặc định của LL.
    """
    added, removed, updated = 0, 0, 0

    from apps.attendance.models import AttendanceCode, AttendanceSettings

    settings = AttendanceSettings.objects.first()
    code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
    if not code_ll:
        code_ll = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()
    code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()

    def _round_time(t):
        if not t:
            return None
        if settings and getattr(settings, "round_registration_to_hour", False):
            return t.replace(minute=0, second=0, microsecond=0)
        return t

    def _clear_times(item):
        item.in1 = None
        item.out1 = None
        item.in2 = None
        item.out2 = None

    def _force_supplement_out(item):
        """BS đi không có mốc giờ và không có thêm giờ tại đơn vị gốc."""
        if code_bs:
            item.code = code_bs
        _clear_times(item)
        if hasattr(item, "overtime_hours"):
            item.overtime_hours = 0

    def _apply_default_times(item, code):
        if not code or not code.is_work:
            _clear_times(item)
            return
        item.in1 = _round_time(code.default_in1) if code.requires_am_work else None
        item.out1 = _round_time(code.default_out1) if code.requires_am_work else None
        item.in2 = _round_time(code.default_in2) if code.requires_pm_work else None
        item.out2 = _round_time(code.default_out2) if code.requires_pm_work else None

    def pick_code_for_direction(direction: str):
        if str(direction) == str(AttendanceBatchItem.BSDirection.OUT) and code_bs:
            return code_bs
        return code_ll or code_bs

    existing = {it.employee_id: it for it in batch.items.select_related("employee", "code")}
    add_emp_ids = [x["employee_id"] for x in diff.get("add", [])]
    emp_qs = Employee.objects.filter(id__in=add_emp_ids)
    emp_map = {e.id: e for e in emp_qs}

    for x in diff.get("add", []):
        emp_id = x["employee_id"]
        if emp_id in existing:
            continue
        emp = emp_map.get(emp_id)
        if not emp:
            continue

        direction = x.get("bs_direction") or AttendanceBatchItem.BSDirection.NONE
        code_obj = pick_code_for_direction(direction)
        if not code_obj:
            continue

        it = AttendanceBatchItem(
            batch=batch,
            employee=emp,
            code=code_obj,
            include_in_unit=bool(x.get("include_in_unit")),
            bs_direction=direction,
            bs_peer_unit_id=x.get("bs_peer_unit_id"),
        )
        if str(direction) == str(AttendanceBatchItem.BSDirection.OUT):
            _force_supplement_out(it)
        else:
            _apply_default_times(it, code_obj)
        it.save()
        added += 1

    for x in diff.get("remove", []):
        emp_id = x["employee_id"]
        it = existing.get(emp_id)
        if not it:
            continue
        if bool(it.include_in_unit):
            it.delete()
            removed += 1

    for x in diff.get("update", []):
        emp_id = x["employee_id"]
        it = existing.get(emp_id)
        if not it:
            continue

        newvals = x.get("new", {})
        old_direction = str(it.bs_direction)
        new_direction = str(newvals.get("bs_direction") or it.bs_direction)
        old_tuple = (bool(it.include_in_unit), old_direction, it.bs_peer_unit_id or None)
        new_tuple = (
            bool(newvals.get("include_in_unit")),
            new_direction,
            newvals.get("bs_peer_unit_id"),
        )
        if old_tuple == new_tuple:
            continue

        it.include_in_unit = new_tuple[0]
        it.bs_direction = new_tuple[1]
        it.bs_peer_unit_id = new_tuple[2]

        if new_direction == str(AttendanceBatchItem.BSDirection.OUT):
            _force_supplement_out(it)
        elif old_direction == str(AttendanceBatchItem.BSDirection.OUT):
            # Người quay lại đơn vị hoặc chuyển sang BS đến: bỏ mã BS và nạp lại mốc giờ hợp lý.
            if code_ll and (not it.code or it.code.code == "BS"):
                it.code = code_ll
                _apply_default_times(it, code_ll)
            elif it.code and it.code.is_work and not any([it.in1, it.out1, it.in2, it.out2]):
                _apply_default_times(it, it.code)

        it.save(update_fields=[
            "include_in_unit",
            "bs_direction",
            "bs_peer_unit",
            "code",
            "in1",
            "out1",
            "in2",
            "out2",
            "overtime_hours",
        ])
        updated += 1

    return {"added": added, "removed": removed, "updated": updated}


def _date_range_filter(qs, start_date=None, end_date=None):
    if start_date:
        qs = qs.filter(work_date__gte=start_date)
    if end_date:
        qs = qs.filter(work_date__lte=end_date)
    return qs


def _safe_scan_window(ta, start_date=None, end_date=None):
    """
    Giới hạn khoảng scan để thao tác điều động không bị chậm.

    Nếu điều động mở chưa có end_date, chỉ scan từ start_date tới hôm nay + 31 ngày.
    Scan chỉ dùng để cảnh báo batch/commit đã tồn tại, không phải để sửa dữ liệu ngầm.
    """
    scan_start = start_date or ta.start_date
    scan_end = end_date or ta.end_date
    if scan_end is None:
        scan_end = timezone.localdate() + timezone.timedelta(days=31)
    return scan_start, scan_end


def _expected_entry_for_employee(unit, work_date, employee, assignment=None):
    """
    Tính riêng một nhân sự trong roster của một đơn vị/ngày.

    Dùng cho scan ảnh hưởng điều động để tránh build lại toàn bộ roster của cả đơn vị.
    """
    if assignment is None and TempAssignment is not None:
        qs = _effective_temp_assignment_qs(work_date)
        assignment = (
            qs.filter(employee_id=employee.id)
            .select_related("from_unit", "to_unit")
            .order_by("-start_date", "-id")
            .first()
            if qs is not None
            else None
        )

    if assignment:
        if assignment.to_unit_id == unit.id:
            return RosterEntry(
                employee_id=employee.id,
                include_in_unit=True,
                bs_direction=AttendanceBatchItem.BSDirection.IN,
                bs_peer_unit_id=assignment.from_unit_id,
            )
        if assignment.from_unit_id == unit.id:
            return RosterEntry(
                employee_id=employee.id,
                include_in_unit=False,
                bs_direction=AttendanceBatchItem.BSDirection.OUT,
                bs_peer_unit_id=assignment.to_unit_id,
            )
        return None

    if employee.status == Employee.Status.ACTIVE and employee.unit_id == unit.id:
        return RosterEntry(
            employee_id=employee.id,
            include_in_unit=True,
            bs_direction=AttendanceBatchItem.BSDirection.NONE,
            bs_peer_unit_id=None,
        )

    return None


def _item_tuple(obj):
    if obj is None:
        return None
    return (
        bool(getattr(obj, "include_in_unit")),
        str(getattr(obj, "bs_direction")),
        getattr(obj, "bs_peer_unit_id") or None,
    )


def _entry_tuple(entry):
    if entry is None:
        return None
    return (
        bool(entry.include_in_unit),
        str(entry.bs_direction),
        entry.bs_peer_unit_id or None,
    )


def _get_commit_item_model():
    """
    Lấy model item của AttendanceCommit một cách an toàn.
    Trong project hiện tại commit.items đang là related manager.
    """
    try:
        return AttendanceCommit.items.rel.related_model
    except Exception:
        try:
            rel = AttendanceCommit._meta.get_field("items")
            return rel.related_model
        except Exception:
            return None


def _safe_scan_window(ta, start_date=None, end_date=None):
    """
    Giới hạn khoảng scan để thao tác điều động không bị chậm.
    Nếu điều động mở chưa có end_date, chỉ scan từ start_date tới hôm nay + 31 ngày.
    """
    scan_start = start_date or ta.start_date
    scan_end = end_date or ta.end_date
    if scan_end is None:
        scan_end = timezone.localdate() + timezone.timedelta(days=31)
    return scan_start, scan_end


def _expected_entry_for_employee(unit, work_date, employee, assignment=None):
    """
    Tính riêng một nhân sự trong danh sách chấm công của một đơn vị/ngày.
    Dùng cho scan điều động để không phải build lại toàn bộ danh sách đơn vị.
    """
    if assignment is None and TempAssignment is not None:
        qs = _effective_temp_assignment_qs(work_date)
        assignment = (
            qs.filter(employee_id=employee.id)
            .select_related("from_unit", "to_unit")
            .order_by("-start_date", "-id")
            .first()
            if qs is not None
            else None
        )

    if assignment:
        if assignment.to_unit_id == unit.id:
            return RosterEntry(
                employee_id=employee.id,
                include_in_unit=True,
                bs_direction=AttendanceBatchItem.BSDirection.IN,
                bs_peer_unit_id=assignment.from_unit_id,
            )
        if assignment.from_unit_id == unit.id:
            return RosterEntry(
                employee_id=employee.id,
                include_in_unit=False,
                bs_direction=AttendanceBatchItem.BSDirection.OUT,
                bs_peer_unit_id=assignment.to_unit_id,
            )
        return None

    if employee.status == Employee.Status.ACTIVE and employee.unit_id == unit.id:
        return RosterEntry(
            employee_id=employee.id,
            include_in_unit=True,
            bs_direction=AttendanceBatchItem.BSDirection.NONE,
            bs_peer_unit_id=None,
        )

    return None


def _item_tuple(obj):
    if obj is None:
        return None
    return (
        bool(getattr(obj, "include_in_unit")),
        str(getattr(obj, "bs_direction")),
        getattr(obj, "bs_peer_unit_id") or None,
    )


def _entry_tuple(entry):
    if entry is None:
        return None
    return (
        bool(entry.include_in_unit),
        str(entry.bs_direction),
        entry.bs_peer_unit_id or None,
    )


def _get_commit_item_model():
    try:
        return AttendanceCommit.items.rel.related_model
    except Exception:
        try:
            rel = AttendanceCommit._meta.get_field("items")
            return rel.related_model
        except Exception:
            return None


def scan_impacts_for_temp_assignment(ta: "TempAssignment", *, start_date=None, end_date=None) -> Dict:
    """
    Kiểm tra điều động ảnh hưởng tới bảng công, tối ưu theo đúng nhân sự bị điều động.

    Quy tắc:
    - Không tự sửa batch/commit.
    - Không build lại toàn bộ danh sách chấm công của đơn vị.
    - Chỉ so sánh dòng của nhân sự điều động trong batch/commit đã tồn tại.
    """
    empty = {
        "draft_batches": 0,
        "committed_batches": 0,
        "draft_items_changed": 0,
        "committed_items_changed": 0,
        "impacted_batch_ids": [],
        "impacted_commit_ids": [],
    }

    if not ta or not getattr(ta, "employee_id", None):
        return empty

    employee = Employee.objects.select_related("unit").filter(pk=ta.employee_id).first()
    if not employee:
        return empty

    unit_ids = [u for u in [ta.from_unit_id, ta.to_unit_id] if u]
    scan_start, scan_end = _safe_scan_window(ta, start_date=start_date, end_date=end_date)

    batch_qs = AttendanceBatch.objects.filter(unit_id__in=unit_ids).select_related("unit")
    commit_qs = AttendanceCommit.objects.filter(unit_id__in=unit_ids).select_related("unit")
    batch_qs = _date_range_filter(batch_qs, scan_start, scan_end)
    commit_qs = _date_range_filter(commit_qs, scan_start, scan_end)

    batch_list = list(batch_qs)
    commit_list = list(commit_qs)
    batch_ids = [b.id for b in batch_list]
    commit_ids = [c.id for c in commit_list]

    batch_items = {
        item.batch_id: item
        for item in AttendanceBatchItem.objects.filter(batch_id__in=batch_ids, employee_id=employee.id)
    }

    commit_items = {}
    commit_item_model = _get_commit_item_model()
    if commit_item_model is not None and commit_ids:
        try:
            commit_items = {
                item.commit_id: item
                for item in commit_item_model.objects.filter(commit_id__in=commit_ids, employee_id=employee.id)
            }
        except Exception:
            commit_items = {}

    assignment_by_date = {}

    def assignment_for_day(day):
        if day not in assignment_by_date:
            qs = _effective_temp_assignment_qs(day)
            assignment_by_date[day] = (
                qs.filter(employee_id=employee.id)
                .select_related("from_unit", "to_unit")
                .order_by("-start_date", "-id")
                .first()
                if qs is not None
                else None
            )
        return assignment_by_date[day]

    draft_batches = 0
    committed_batches = 0
    draft_items_changed = 0
    committed_items_changed = 0
    impacted_batch_ids = []
    impacted_commit_ids = []

    for batch in batch_list:
        entry = _expected_entry_for_employee(
            batch.unit,
            batch.work_date,
            employee,
            assignment=assignment_for_day(batch.work_date),
        )
        current = batch_items.get(batch.id)
        if _entry_tuple(entry) != _item_tuple(current):
            draft_batches += 1
            draft_items_changed += 1
            impacted_batch_ids.append(batch.id)

    for commit in commit_list:
        entry = _expected_entry_for_employee(
            commit.unit,
            commit.work_date,
            employee,
            assignment=assignment_for_day(commit.work_date),
        )
        current = commit_items.get(commit.id)
        if current is None:
            try:
                current = commit.items.filter(employee_id=employee.id).first()
            except Exception:
                current = None

        if _entry_tuple(entry) != _item_tuple(current):
            committed_batches += 1
            committed_items_changed += 1
            impacted_commit_ids.append(commit.id)

            if Notification:
                try:
                    Notification.objects.create(
                        user=None,
                        title=f"Điều động ảnh hưởng công đã chốt ({commit.unit.symbol})",
                        body=f"Ngày {commit.work_date}: nhân sự {employee.employee_code} có thay đổi danh sách chấm công do điều động.",
                        url=f"/backoffice/attendance/committed/?date={commit.work_date}&unit={commit.unit_id}",
                    )
                except Exception:
                    pass

    summary = {
        "draft_batches": draft_batches,
        "committed_batches": committed_batches,
        "draft_items_changed": draft_items_changed,
        "committed_items_changed": committed_items_changed,
        "impacted_batch_ids": impacted_batch_ids[:100],
        "impacted_commit_ids": impacted_commit_ids[:100],
        "scan_start": scan_start.isoformat() if scan_start else None,
        "scan_end": scan_end.isoformat() if scan_end else None,
        "scan_mode": "employee_only",
    }

    try:
        ta.last_impact_scan_at = timezone.now()
        ta.last_impact_summary = summary
        ta.save(update_fields=["last_impact_scan_at", "last_impact_summary"])
    except Exception:
        pass

    return summary
