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

# NEW: cần Employee để tạo commit item khi ADD_EMPLOYEE
try:
    from apps.hr.models import Employee
except Exception:
    Employee = None

User = get_user_model()


def _parse_time_str(val: Optional[str]):
    """
    Chấp nhận None, 'HH:MM', 'HH:MM:SS'
    """
    if not val:
        return None
    try:
        parts = str(val).split(":")
        hh = int(parts[0]); mm = int(parts[1]); ss = int(parts[2]) if len(parts) > 2 else 0
        from datetime import time as dt_time
        return dt_time(hh, mm, ss)
    except Exception:
        return None


def apply_correction_request(acr_id: int, actor: User) -> Dict[str, Any]:
    """
    Áp dụng thay đổi từ AttendanceCorrectionRequest.payload_json vào công đã chốt cùng ngày/đơn vị.
    Idempotent: nếu ACR đã APPLIED => return ngay (không áp dụng lại).

    Định dạng payload_json mong đợi:
      - Field-level: [{employee_id, employee_code?, field, old, new}, ...] với field ∈ {code, in1, out1, in2, out2, notes, include_in_unit}
      - Membership-level:
        + {"type":"ADD_EMPLOYEE", ...}
        + {"type":"REMOVE_EMPLOYEE","employee_id":...}  -> HARD REMOVE: xoá commit item
    """
    acr = AttendanceCorrectionRequest.objects.select_related("unit").filter(id=acr_id).first()
    if not acr:
        return {"ok": False, "error": "ACR not found"}

    # Idempotent
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

    # Helper: pick default code when needed
    def _pick_default_code():
        code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
        if code_ll:
            return code_ll
        return AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()

    with transaction.atomic():
        for ch in changes:
            op_type = (ch.get("type") or "").upper()

            # ADD_EMPLOYEE: tạo mới nếu chưa có; nếu có thì bật include_in_unit=True và cập nhật
            if op_type == "ADD_EMPLOYEE":
                emp_id = ch.get("employee_id")
                if not emp_id:
                    continue
                item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()
                if not item and Employee is not None:
                    emp = Employee.objects.filter(id=emp_id).first()
                    if not emp:
                        continue
                    code_val = ch.get("code")
                    code_obj = AttendanceCode.objects.filter(code=str(code_val).strip(), is_active=True).first() if code_val else None
                    if not code_obj:
                        code_obj = _pick_default_code()
                    item = AttendanceCommitItem.objects.create(
                        commit=commit,
                        employee=emp,
                        code=code_obj,
                        shift=getattr(AttendanceCommitItem.Shift, "DAY", "DAY"),
                        in1=_parse_time_str(ch.get("in1")),
                        out1=_parse_time_str(ch.get("out1")),
                        in2=_parse_time_str(ch.get("in2")),
                        out2=_parse_time_str(ch.get("out2")),
                        notes=ch.get("notes") or "",
                        bs_direction=getattr(AttendanceCommitItem.BSDirection, "NONE", "NONE"),
                        bs_peer_unit=None,
                        include_in_unit=True,
                    )
                    applied_rows += 1
                    deltas.append({
                        "employee_id": emp_id,
                        "field": "ADD_EMPLOYEE",
                        "old": None,
                        "new": {
                            "code": item.code.code if item.code else None,
                            "in1": item.in1 and item.in1.strftime("%H:%M"),
                            "out1": item.out1 and item.out1.strftime("%H:%M"),
                            "in2": item.in2 and item.in2.strftime("%H:%M"),
                            "out2": item.out2 and item.out2.strftime("%H:%M"),
                            "include_in_unit": item.include_in_unit,
                        },
                    })
                    continue

                if item:
                    prev = {
                        "include_in_unit": bool(item.include_in_unit),
                        "code": item.code.code if item.code else None,
                        "in1": item.in1 and item.in1.strftime("%H:%M"),
                        "out1": item.out1 and item.out1.strftime("%H:%M"),
                        "in2": item.in2 and item.in2.strftime("%H:%M"),
                        "out2": item.out2 and item.out2.strftime("%H:%M"),
                    }
                    item.include_in_unit = True
                    code_val = ch.get("code")
                    if code_val:
                        code_obj = AttendanceCode.objects.filter(code=str(code_val).strip(), is_active=True).first()
                        if code_obj and (not item.code or item.code_id != code_obj.id):
                            item.code = code_obj
                    for fname in ("in1", "out1", "in2", "out2"):
                        if fname in ch:
                            setattr(item, fname, _parse_time_str(ch.get(fname)))
                    if "notes" in ch:
                        item.notes = ch.get("notes") or ""
                    item.save()
                    applied_rows += 1
                    deltas.append({"employee_id": emp_id, "field": "ADD_EMPLOYEE_UPDATE", "old": prev, "new": {
                        "include_in_unit": item.include_in_unit,
                        "code": item.code.code if item.code else None,
                        "in1": item.in1 and item.in1.strftime("%H:%M"),
                        "out1": item.out1 and item.out1.strftime("%H:%M"),
                        "in2": item.in2 and item.in2.strftime("%H:%M"),
                        "out2": item.out2 and item.out2.strftime("%H:%M"),
                    }})
                    continue

            # REMOVE_EMPLOYEE: HARD REMOVE -> xoá commit item
            if op_type == "REMOVE_EMPLOYEE":
                emp_id = ch.get("employee_id")
                if not emp_id:
                    continue
                item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()
                if not item:
                    continue
                prev = {
                    "include_in_unit": bool(item.include_in_unit),
                    "code": item.code.code if item.code else None,
                    "in1": item.in1 and item.in1.strftime("%H:%M"),
                    "out1": item.out1 and item.out1.strftime("%H:%M"),
                    "in2": item.in2 and item.in2.strftime("%H:%M"),
                    "out2": item.out2 and item.out2.strftime("%H:%M"),
                }
                item.delete()
                applied_rows += 1
                deltas.append({"employee_id": emp_id, "field": "REMOVE_EMPLOYEE", "old": prev, "new": None})
                continue

            # Field-level operations
            emp_id = ch.get("employee_id")
            field = ch.get("field")
            if not emp_id or not field:
                continue

            new = ch.get("new")
            item = AttendanceCommitItem.objects.filter(commit_id=commit.id, employee_id=emp_id).first()
            if not item:
                continue

            prev = getattr(item, field, None) if hasattr(item, field) else None

            if field in ("in1", "out1", "in2", "out2"):
                new_time = _parse_time_str(new)
                if (prev or None) == (new_time or None):
                    continue
                setattr(item, field, new_time)
            elif field == "code":
                if not new:
                    continue
                new_code = AttendanceCode.objects.filter(code=str(new).strip(), is_active=True).first()
                if not new_code:
                    continue
                if item.code_id == new_code.id:
                    continue
                prev = item.code.code if item.code else None
                item.code = new_code
            elif field == "notes":
                if (prev or "") == (new or ""):
                    continue
                setattr(item, field, new or "")
            elif field == "include_in_unit":
                new_bool = bool(new)
                if bool(prev) == new_bool:
                    continue
                setattr(item, field, new_bool)
            else:
                continue

            item.save()
            applied_rows += 1
            deltas.append({
                "employee_id": emp_id,
                "field": field,
                "old": prev if field != "code" else prev,
                "new": new,
            })

        # Cập nhật trạng thái ACR
        acr.status = applied_status
        acr.applied_at = timezone.now()
        if not getattr(acr, "approved_hr_by_id", None) and actor and getattr(actor, "id", None):
            acr.approved_hr_by = actor
        acr.save(update_fields=["status", "applied_at", "approved_hr_by"])

    # Đồng bộ nháp theo commit: sau khi REMOVE (xoá hẳn item), batch sẽ phản ánh đúng
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