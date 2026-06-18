from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from apps.attendance.models import AttendanceCode
from apps.attendance.models_batch import AttendanceCorrectionRequest, AttendanceCommit, AttendanceCommitItem
from apps.audit.utils import audit_log

# Đồng bộ nháp theo công chốt sau khi apply
try:
    from apps.attendance.services_sync import sync_batch_with_commit
except Exception:
    sync_batch_with_commit = None

# Cần Employee để tạo commit item khi ADD_EMPLOYEE
try:
    from apps.hr.models import Employee
except Exception:
    Employee = None

User = get_user_model()


def _parse_time_str(val: Optional[str]):
    """
    Chấp nhận None, 'HH:MM', 'HH:MM:SS'.
    """
    if not val:
        return None
    try:
        parts = str(val).split(":")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        from datetime import time as dt_time
        return dt_time(hh, mm, ss)
    except Exception:
        return None


def _parse_bool(val, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    text = str(val).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "có", "co"}:
        return True
    if text in {"0", "false", "no", "n", "off", "không", "khong", ""}:
        return False
    return default


def _parse_int_or_none(val):
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _clamp_overtime(val) -> int:
    try:
        hours = int(val or 0)
    except (TypeError, ValueError):
        hours = 0
    return max(0, min(4, hours))


def _item_state(item: AttendanceCommitItem) -> Dict[str, Any]:
    return {
        "include_in_unit": bool(item.include_in_unit),
        "bs_direction": item.bs_direction,
        "bs_peer_unit_id": item.bs_peer_unit_id,
        "code": item.code.code if item.code else None,
        "in1": item.in1 and item.in1.strftime("%H:%M"),
        "out1": item.out1 and item.out1.strftime("%H:%M"),
        "in2": item.in2 and item.in2.strftime("%H:%M"),
        "out2": item.out2 and item.out2.strftime("%H:%M"),
        "overtime_hours": int(getattr(item, "overtime_hours", 0) or 0),
        "notes": item.notes or "",
    }


def _pick_default_code():
    code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
    if code_ll:
        return code_ll
    return AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()


def _code_by_code(code_value: Optional[str]):
    if not code_value:
        return None
    return AttendanceCode.objects.filter(code=str(code_value).strip(), is_active=True).first()


def _normalize_commit_item_after_correction(item: AttendanceCommitItem) -> bool:
    """
    Chuẩn hóa cuối sau khi áp dụng sửa công.

    - BS đi/OUT là dòng công hợp lệ của đơn vị gốc, nhưng không tính trong đơn vị,
      bắt buộc dùng mã BS, không có mốc giờ và không có thêm giờ.
    - Mã không đi làm thì không giữ mốc IN/OUT và thêm giờ.
    - Sau mỗi lần chuẩn hóa phải snapshot lại để báo cáo và thiết bị v2 dùng đúng mốc đã chốt.
    """
    changed = False
    out_direction = getattr(AttendanceCommitItem.BSDirection, "OUT", "OUT")
    if str(item.bs_direction) == str(out_direction):
        code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()
        if code_bs and item.code_id != code_bs.id:
            item.code = code_bs
            changed = True
        if item.include_in_unit:
            item.include_in_unit = False
            changed = True
        for fname in ("in1", "out1", "in2", "out2"):
            if getattr(item, fname):
                setattr(item, fname, None)
                changed = True
        if int(getattr(item, "overtime_hours", 0) or 0) != 0:
            item.overtime_hours = 0
            changed = True
    elif item.code and not bool(getattr(item.code, "is_work", False)):
        for fname in ("in1", "out1", "in2", "out2"):
            if getattr(item, fname):
                setattr(item, fname, None)
                changed = True
        if int(getattr(item, "overtime_hours", 0) or 0) != 0:
            item.overtime_hours = 0
            changed = True

    item.apply_code_snapshot()
    return changed


def apply_correction_request(acr_id: int, actor: User) -> Dict[str, Any]:
    """
    Áp dụng thay đổi từ AttendanceCorrectionRequest.payload_json vào công đã chốt cùng ngày/đơn vị.
    Idempotent: nếu ACR đã APPLIED => return ngay.

    Payload hỗ trợ:
      - Field-level: code, in1/out1/in2/out2, overtime_hours, notes, include_in_unit,
        bs_direction, bs_peer_unit_id.
      - Membership-level:
        + ADD_EMPLOYEE: thêm dòng công chốt hợp lệ, bao gồm cả BS đi include_in_unit=False.
        + REMOVE_EMPLOYEE: chỉ xóa khi nhân sự thật sự không còn trong nháp.
    """
    acr = AttendanceCorrectionRequest.objects.select_related("unit").filter(id=acr_id).first()
    if not acr:
        return {"ok": False, "error": "ACR not found"}

    try:
        applied_status = AttendanceCorrectionRequest.Status.APPLIED
    except Exception:
        applied_status = "APPLIED"
    if getattr(acr, "status", "") == applied_status:
        return {"ok": True, "applied_rows": 0, "deltas": [], "note": "Already applied"}

    commit = AttendanceCommit.objects.filter(unit_id=acr.unit_id, work_date=acr.work_date).first()
    if not commit:
        return {"ok": False, "error": "No committed data for unit/date"}

    changes = acr.payload_json or []
    applied_rows = 0
    deltas: List[Dict[str, Any]] = []

    with transaction.atomic():
        for ch in changes:
            op_type = (ch.get("type") or "").upper()

            if op_type == "ADD_EMPLOYEE":
                emp_id = ch.get("employee_id")
                if not emp_id:
                    continue
                item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()

                if not item and Employee is not None:
                    emp = Employee.objects.filter(id=emp_id).first()
                    if not emp:
                        continue
                    code_obj = _code_by_code(ch.get("code")) or _pick_default_code()
                    if not code_obj:
                        continue
                    item = AttendanceCommitItem(
                        commit=commit,
                        employee=emp,
                        code=code_obj,
                        shift=getattr(AttendanceCommitItem.Shift, "DAY", "DAY"),
                        in1=_parse_time_str(ch.get("in1")),
                        out1=_parse_time_str(ch.get("out1")),
                        in2=_parse_time_str(ch.get("in2")),
                        out2=_parse_time_str(ch.get("out2")),
                        overtime_hours=_clamp_overtime(ch.get("overtime_hours")),
                        notes=ch.get("notes") or "",
                        bs_direction=ch.get("bs_direction") or getattr(AttendanceCommitItem.BSDirection, "NONE", "NONE"),
                        bs_peer_unit_id=_parse_int_or_none(ch.get("bs_peer_unit_id")),
                        include_in_unit=_parse_bool(ch.get("include_in_unit"), default=True),
                    )
                    _normalize_commit_item_after_correction(item)
                    item.save()
                    applied_rows += 1
                    deltas.append({"employee_id": emp_id, "field": "ADD_EMPLOYEE", "old": None, "new": _item_state(item)})
                    continue

                if item:
                    prev = _item_state(item)
                    item.include_in_unit = _parse_bool(ch.get("include_in_unit"), default=bool(item.include_in_unit))
                    if "bs_direction" in ch:
                        item.bs_direction = ch.get("bs_direction") or getattr(AttendanceCommitItem.BSDirection, "NONE", "NONE")
                    if "bs_peer_unit_id" in ch:
                        item.bs_peer_unit_id = _parse_int_or_none(ch.get("bs_peer_unit_id"))
                    code_obj = _code_by_code(ch.get("code"))
                    if code_obj:
                        item.code = code_obj
                    for fname in ("in1", "out1", "in2", "out2"):
                        if fname in ch:
                            setattr(item, fname, _parse_time_str(ch.get(fname)))
                    if "overtime_hours" in ch:
                        item.overtime_hours = _clamp_overtime(ch.get("overtime_hours"))
                    if "notes" in ch:
                        item.notes = ch.get("notes") or ""
                    _normalize_commit_item_after_correction(item)
                    if _item_state(item) == prev:
                        continue
                    item.save()
                    applied_rows += 1
                    deltas.append({"employee_id": emp_id, "field": "ADD_EMPLOYEE_UPDATE", "old": prev, "new": _item_state(item)})
                    continue

            if op_type == "REMOVE_EMPLOYEE":
                emp_id = ch.get("employee_id")
                if not emp_id:
                    continue
                item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()
                if not item:
                    continue
                prev = _item_state(item)
                item.delete()
                applied_rows += 1
                deltas.append({"employee_id": emp_id, "field": "REMOVE_EMPLOYEE", "old": prev, "new": None})
                continue

            emp_id = ch.get("employee_id")
            field = ch.get("field")
            if not emp_id or not field:
                continue

            new = ch.get("new")
            item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()
            if not item:
                continue

            prev_state = _item_state(item)
            old_value = None

            if field in ("in1", "out1", "in2", "out2"):
                old_value = getattr(item, field)
                setattr(item, field, _parse_time_str(new))
            elif field == "code":
                new_code = _code_by_code(new)
                if not new_code:
                    continue
                old_value = item.code.code if item.code else None
                item.code = new_code
            elif field == "overtime_hours":
                old_value = int(getattr(item, "overtime_hours", 0) or 0)
                item.overtime_hours = _clamp_overtime(new)
            elif field == "notes":
                old_value = item.notes or ""
                item.notes = new or ""
            elif field == "include_in_unit":
                old_value = bool(item.include_in_unit)
                item.include_in_unit = _parse_bool(new, default=bool(item.include_in_unit))
            elif field == "bs_direction":
                old_value = item.bs_direction or getattr(AttendanceCommitItem.BSDirection, "NONE", "NONE")
                item.bs_direction = new or getattr(AttendanceCommitItem.BSDirection, "NONE", "NONE")
            elif field == "bs_peer_unit_id":
                old_value = item.bs_peer_unit_id
                item.bs_peer_unit_id = _parse_int_or_none(new)
            else:
                continue

            _normalize_commit_item_after_correction(item)
            new_state = _item_state(item)
            if new_state == prev_state:
                continue
            item.save()
            applied_rows += 1
            deltas.append({
                "employee_id": emp_id,
                "field": field,
                "old": old_value,
                "new": new,
                "normalized": new_state,
            })

        acr.status = applied_status
        acr.applied_at = timezone.now()
        if not getattr(acr, "approved_hr_by_id", None) and actor and getattr(actor, "id", None):
            acr.approved_hr_by = actor
        acr.save(update_fields=["status", "applied_at", "approved_hr_by"])

    if sync_batch_with_commit:
        try:
            sync_batch_with_commit(unit_id=acr.unit_id, work_date=acr.work_date)
        except Exception:
            pass

    audit_log(
        action_verb="APPLY",
        object_type="attendance_correction",
        object_id=acr.id,
        object_repr=f"{acr.unit.code}-{acr.work_date}",
        actor=actor,
        changes={"applied_rows": applied_rows, "deltas": deltas},
        request=None,
        action_code="ATT_CORRECTION_APPLY"
    )

    return {"ok": True, "applied_rows": applied_rows, "deltas": deltas}
