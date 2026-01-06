from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from datetime import date as dt_date
import hashlib

from django.db import transaction

from apps.organization.models import OrgUnit
from apps.hr.models import Employee
try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None

from apps.attendance.models_batch import AttendanceBatch, AttendanceBatchItem, AttendanceCommit, AttendanceCommitItem

# Optional notifications
try:
    from apps.notifications.models import Notification
except Exception:
    Notification = None


@dataclass(frozen=True)
class RosterEntry:
    employee_id: int
    include_in_unit: bool
    bs_direction: str  # "NONE" | "IN" | "OUT"
    bs_peer_unit_id: Optional[int]


def _active_bs_in_ids(unit: OrgUnit, work_date: dt_date) -> List[int]:
    if TempAssignment is None:
        return []
    qs = TempAssignment.objects.filter(
        apply_flag=True, status="ACTIVE",
        to_unit=unit,
        start_date__lte=work_date
    )
    # end_date có thể null => coi như vô hạn
    qs = qs.filter(end_date__isnull=True) | qs.filter(end_date__gte=work_date)
    return list(qs.values_list("employee_id", flat=True))


def _active_bs_out_ids(unit: OrgUnit, work_date: dt_date) -> List[int]:
    if TempAssignment is None:
        return []
    qs = TempAssignment.objects.filter(
        apply_flag=True, status="ACTIVE",
        from_unit=unit,
        start_date__lte=work_date
    )
    qs = qs.filter(end_date__isnull=True) | qs.filter(end_date__gte=work_date)
    return list(qs.values_list("employee_id", flat=True))


def build_expected_roster(unit: OrgUnit, work_date: dt_date, team_id: Optional[int] = None) -> List[RosterEntry]:
    """
    Tổ hợp roster kỳ vọng cho đơn vị/ngày dựa vào:
    - Nhân sự ACTIVE thuộc đơn vị
    - BS IN vào đơn vị
    - BS OUT khỏi đơn vị
    Quy tắc include_in_unit:
      - Nếu BS_OUT và không BS_IN -> include_in_unit=False, bs_direction=OUT
      - Nếu BS_IN và không BS_OUT -> include_in_unit=True, bs_direction=IN
      - Nếu cả hai hoặc không cái nào -> include_in_unit=True, bs_direction=NONE
    """
    base_qs = Employee.objects.filter(unit=unit, status=Employee.Status.ACTIVE)
    if team_id:
        base_qs = base_qs.filter(team_id=team_id)
    base_ids = set(base_qs.values_list("id", flat=True))

    bs_in_ids = set(_active_bs_in_ids(unit, work_date))
    bs_out_ids = set(_active_bs_out_ids(unit, work_date))

    # Union: tất cả nhân sự có liên quan
    all_ids = base_ids.union(bs_in_ids).union(bs_out_ids)

    # Peer unit cho BS OUT: chỉ là thông tin snapshot nếu cần (không luôn xác định được ở đây)
    peer_unit_map: Dict[int, Optional[int]] = {}
    if TempAssignment is not None:
        # Lấy peer unit id theo điều động đang active (ưu tiên to_unit cho IN, from_unit cho OUT)
        ta_qs = TempAssignment.objects.filter(
            apply_flag=True, status="ACTIVE",
            start_date__lte=work_date
        ).filter(end_date__isnull=True) | TempAssignment.objects.filter(
            apply_flag=True, status="ACTIVE",
            start_date__lte=work_date, end_date__gte=work_date
        )
        for ta in ta_qs.select_related("from_unit", "to_unit", "employee"):
            if ta.to_unit_id == unit.id:
                peer_unit_map[ta.employee_id] = getattr(ta.from_unit, "id", None)
            elif ta.from_unit_id == unit.id:
                peer_unit_map[ta.employee_id] = getattr(ta.to_unit, "id", None)

    roster: List[RosterEntry] = []
    for emp_id in sorted(all_ids):
        in_in = emp_id in bs_in_ids
        in_out = emp_id in bs_out_ids
        if in_out and not in_in:
            roster.append(RosterEntry(
                employee_id=emp_id,
                include_in_unit=False,
                bs_direction=AttendanceBatchItem.BSDirection.OUT,
                bs_peer_unit_id=peer_unit_map.get(emp_id)
            ))
        elif in_in and not in_out:
            roster.append(RosterEntry(
                employee_id=emp_id,
                include_in_unit=True,
                bs_direction=AttendanceBatchItem.BSDirection.IN,
                bs_peer_unit_id=peer_unit_map.get(emp_id)
            ))
        else:
            roster.append(RosterEntry(
                employee_id=emp_id,
                include_in_unit=True,
                bs_direction=AttendanceBatchItem.BSDirection.NONE,
                bs_peer_unit_id=peer_unit_map.get(emp_id)
            ))
    return roster


def compute_roster_signature(entries: List[RosterEntry]) -> str:
    """
    Tạo signature (SHA1) từ danh sách roster kỳ vọng (hoặc từ batch items đã map).
    """
    key_parts = [f"{e.employee_id}:{int(e.include_in_unit)}:{e.bs_direction}:{e.bs_peer_unit_id or ''}" for e in entries]
    joined = "|".join(key_parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def batch_roster_signature(batch: AttendanceBatch) -> str:
    """
    Tạo signature từ roster hiện có trong batch (composition only),
    không đụng đến mã chế độ hay mốc thời gian.
    """
    items = list(batch.items.values("employee_id", "include_in_unit", "bs_direction", "bs_peer_unit_id").order_by("employee_id"))
    entries = [
        RosterEntry(
            employee_id=it["employee_id"],
            include_in_unit=bool(it["include_in_unit"]),
            bs_direction=it["bs_direction"],
            bs_peer_unit_id=it["bs_peer_unit_id"]
        )
        for it in items
    ]
    return compute_roster_signature(entries)


def compute_roster_diff(batch: AttendanceBatch, expected: List[RosterEntry]) -> Dict[str, List[Dict]]:
    """
    So sánh roster của batch với expected -> trả về diff:
    - add: nhân sự có trong expected nhưng không có dòng trong batch
    - remove: nhân sự có trong batch nhưng không còn trong expected với include_in_unit=True (và không phải BS_OUT)
    - update: nhân sự cần đổi include_in_unit/bs_direction/bs_peer_unit_id
    Lưu ý: không đụng tới code/time (giữ nguyên dữ liệu nhập tay).
    """
    exp_map: Dict[int, RosterEntry] = {e.employee_id: e for e in expected}
    batch_map: Dict[int, AttendanceBatchItem] = {it.employee_id: it for it in batch.items.all()}

    add, remove, update = [], [], []

    # Add or update
    for emp_id, e in exp_map.items():
        it = batch_map.get(emp_id)
        if not it:
            add.append({
                "employee_id": emp_id,
                "include_in_unit": e.include_in_unit,
                "bs_direction": e.bs_direction,
                "bs_peer_unit_id": e.bs_peer_unit_id
            })
        else:
            need_update = (
                bool(it.include_in_unit) != bool(e.include_in_unit) or
                str(it.bs_direction) != str(e.bs_direction) or
                (it.bs_peer_unit_id or None) != (e.bs_peer_unit_id or None)
            )
            if need_update:
                update.append({
                    "employee_id": emp_id,
                    "old": {
                        "include_in_unit": bool(it.include_in_unit),
                        "bs_direction": str(it.bs_direction),
                        "bs_peer_unit_id": it.bs_peer_unit_id
                    },
                    "new": {
                        "include_in_unit": bool(e.include_in_unit),
                        "bs_direction": str(e.bs_direction),
                        "bs_peer_unit_id": e.bs_peer_unit_id
                    }
                })

    # Remove: nhân sự chỉ tồn tại trong batch và expected cho thấy phải loại (trường hợp hiếm).
    for emp_id, it in batch_map.items():
        if emp_id not in exp_map:
            # Nếu không có trong expected, và dòng hiện tại include_in_unit=True, coi là remove
            # Nếu dòng đang BS_OUT (include_in_unit=False), giữ lại để người dùng tham chiếu.
            if bool(it.include_in_unit):
                remove.append({
                    "employee_id": emp_id,
                    "include_in_unit": bool(it.include_in_unit),
                    "bs_direction": str(it.bs_direction),
                    "bs_peer_unit_id": it.bs_peer_unit_id
                })

    return {"add": add, "remove": remove, "update": update}


@transaction.atomic
def apply_roster_diff(batch: AttendanceBatch, diff: Dict[str, List[Dict]]) -> Dict[str, int]:
    """
    Áp dụng diff roster vào batch:
    - add: thêm AttendanceBatchItem mới với code mặc định giữ nguyên như hiện tại (không áp code/time).
      -> code set theo LL (nếu có) hoặc bản ghi đầu tiên active theo priority (có thể tuỳ chỉnh bên ngoài).
    - remove: xoá dòng (chỉ khi include_in_unit=True); nếu dòng là BS_OUT -> không remove.
    - update: cập nhật include_in_unit/bs_direction/bs_peer_unit_id.
    """
    added, removed, updated = 0, 0, 0

    # Code mặc định cho add
    from apps.attendance.models import AttendanceCode
    code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
    if not code_ll:
        code_ll = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()

    # Maps tiện dụng
    existing = {it.employee_id: it for it in batch.items.select_related("employee", "code")}
    emp_qs = Employee.objects.filter(id__in=[x["employee_id"] for x in diff.get("add", [])])

    # Add
    emp_map = {e.id: e for e in emp_qs}
    for x in diff.get("add", []):
        emp_id = x["employee_id"]
        if emp_id in existing:
            continue
        emp = emp_map.get(emp_id)
        if not emp:
            continue
        it = AttendanceBatchItem(
            batch=batch,
            employee=emp,
            code=code_ll,
            include_in_unit=bool(x.get("include_in_unit")),
            bs_direction=x.get("bs_direction") or AttendanceBatchItem.BSDirection.NONE,
            bs_peer_unit_id=x.get("bs_peer_unit_id"),
        )
        it.save()
        added += 1

    # Remove
    for x in diff.get("remove", []):
        emp_id = x["employee_id"]
        it = existing.get(emp_id)
        if not it:
            continue
        # Chỉ remove nếu dòng hiện include_in_unit=True
        if bool(it.include_in_unit):
            it.delete()
            removed += 1

    # Update
    for x in diff.get("update", []):
        emp_id = x["employee_id"]
        it = existing.get(emp_id)
        if not it:
            continue
        newvals = x.get("new", {})
        it.include_in_unit = bool(newvals.get("include_in_unit"))
        it.bs_direction = newvals.get("bs_direction") or it.bs_direction
        it.bs_peer_unit_id = newvals.get("bs_peer_unit_id")
        it.save(update_fields=["include_in_unit", "bs_direction", "bs_peer_unit_id"])
        updated += 1

    return {"added": added, "removed": removed, "updated": updated}


def scan_impacts_for_temp_assignment(ta: "TempAssignment") -> Dict[str, int]:
    """
    Kiểm tra ảnh hưởng của điều động tạm thời tới các ngày đã chốt.
    - Nếu có commit trong khoảng ngày [start_date..end_date] (hoặc open-ended), tạo thông báo cho HR/đơn vị.
    - Không tự sửa commit; chỉ gửi Notification hoặc ghi log (tuỳ có model Notification).
    Trả về số lượng ngày commit bị ảnh hưởng.
    """
    if not ta or not getattr(ta, "to_unit", None):
        return {"impacted_days": 0}

    # Range ngày
    start = ta.start_date
    end = ta.end_date

    # Nếu end_date None -> lấy tới max ngày commit hiện có cho đơn vị
    commits_qs = AttendanceCommit.objects.filter(
        unit_id__in=[ta.to_unit_id, ta.from_unit_id] if ta.from_unit_id else [ta.to_unit_id]
    )
    if start:
        commits_qs = commits_qs.filter(work_date__gte=start)
    if end:
        commits_qs = commits_qs.filter(work_date__lte=end)

    impacted = 0
    for cm in commits_qs.select_related("unit"):
        # Tính expected roster cho ngày commit với đơn vị tương ứng (to_unit)
        unit = cm.unit
        exp = build_expected_roster(unit, cm.work_date)
        exp_ids = {e.employee_id for e in exp if e.include_in_unit}
        # Roster trong commit
        commit_ids = set(cm.items.filter(include_in_unit=True).values_list("employee_id", flat=True))
        if exp_ids != commit_ids:
            impacted += 1
            if Notification:
                try:
                    Notification.objects.create(
                        user=None,  # có thể chọn HR group hoặc admin sau
                        title=f"Ảnh hưởng điều động tới công đã chốt ({unit.symbol})",
                        body=f"Ngày {cm.work_date}: roster kỳ vọng khác công chốt (Δ={len(exp_ids ^ commit_ids)}).",
                        url=f"/backoffice/attendance/committed/?date={cm.work_date}&unit={unit.id}"
                    )
                except Exception:
                    pass

    return {"impacted_days": impacted}