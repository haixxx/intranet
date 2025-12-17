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
    Sau khi áp dụng xong, đồng bộ AttendanceBatchItem theo AttendanceCommitItem.

    Định dạng payload_json mong đợi:
      [{employee_id, employee_code?, field, old, new}, ...]
    Hỗ trợ field: code, in1, out1, in2, out2, notes, include_in_unit.
    """
    acr = AttendanceCorrectionRequest.objects.select_related("unit").filter(id=acr_id).first()
    if not acr:
        return {"ok": False, "error": "ACR not found"}

    # Idempotent: nếu đã APPLIED thì không áp dụng lại
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
            emp_id = ch.get("employee_id")
            field = ch.get("field")
            if not emp_id or not field:
                continue

            new = ch.get("new")
            # Cho phép new là False/0, nên không loại bỏ theo new is None khi field là boolean/text
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
                # new là mã AttendanceCode (string). Đổi mã code nếu tìm thấy.
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
                # Field ngoài whitelist: bỏ qua để an toàn
                continue

            item.save()
            applied_rows += 1
            deltas.append({
                "employee_id": emp_id,
                "field": field,
                "old": prev if field != "code" else prev,  # prev của code là string ở trên
                "new": new,
            })

        # Cập nhật trạng thái ACR
        acr.status = applied_status
        acr.applied_at = timezone.now()
        if not getattr(acr, "approved_hr_by_id", None) and actor and getattr(actor, "id", None):
            acr.approved_hr_by = actor
        acr.save(update_fields=["status", "applied_at", "approved_hr_by"])

    # Đồng bộ nháp theo công đã chốt sau khi apply (nếu service tồn tại)
    if sync_batch_with_commit:
        try:
            sync_batch_with_commit(unit_id=acr.unit_id, work_date=acr.work_date)
        except Exception:
            # tránh làm vỡ apply nếu đồng bộ lỗi
            pass

    # Audit tổng hợp
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