from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import ApprovalRequest, ApprovalStep, ApprovalSigner, ApprovalAction
from .services_runtime_rolemap import get_role_title_map
from apps.audit.utils import audit_log

# HR/Org dữ liệu thực
try:
    from apps.hr.models import Employee  # Employee có unit, team, status, (có thể có) user liên kết
except Exception:
    Employee = None
try:
    from apps.organization.models import OrgUnit
except Exception:
    OrgUnit = None

# Hook Apply attendance correction
try:
    from apps.attendance.services_apply import apply_correction_request
except Exception:
    apply_correction_request = None
# Notifications
try:
    from apps.notifications.models import Notification
except Exception:
    Notification = None

User = get_user_model()

# Map role_chain chuẩn sang mã chức danh thực tế (fallback khi DB RoleTitleMapping chưa có dữ liệu)
JOB_TITLE_CODE_MAP = {
    "HEAD": {"TruongPhong", "TruongBan", "QuanDoc", "GiamDocXiNghiep"},
    "DEPUTY": {"PhoTruongPhong", "PhoBan", "PhoQuanDoc", "PhoGiamDocXiNghiep"},
    "IN_CHARGE": {"QuanDoc", "GiamDocXiNghiep"},
}

def _get_employee_job_title_code(emp) -> Optional[str]:
    jt = getattr(emp, "job_title", None)
    if not jt:
        return None
    code = getattr(jt, "code", None) or getattr(jt, "title_code", None) or getattr(jt, "symbol", None)
    if not code:
        return None
    return str(code)

def _get_employee_user(emp) -> Optional[User]:
    u = getattr(emp, "user", None)
    if u:
        return u if getattr(u, "is_active", True) else None
    uid = getattr(emp, "user_id", None) or getattr(emp, "account_id", None) or getattr(emp, "auth_user_id", None)
    if uid:
        return User.objects.filter(id=uid, is_active=True).first()
    return None

def _get_excluded_user_ids(request: ApprovalRequest, step: ApprovalStep) -> set[int]:
    """
    Guard nghiệp vụ cho bước lãnh đạo đơn vị.

    Mặc định không cho người lập phiếu tự xuất hiện trong danh sách ký lãnh đạo
    (đặc biệt với luồng sửa công do nhân viên thống kê lập). Nếu một luồng đặc biệt
    muốn cho phép tự ký, có thể đặt resolver.exclude_requester = False.
    """
    rcfg: Dict[str, Any] = step.resolver_config or {}
    excluded: set[int] = set()
    if bool(rcfg.get("exclude_requester", True)) and request.requester_id:
        excluded.add(int(request.requester_id))
    for raw in (rcfg.get("exclude_user_ids") or []):
        try:
            excluded.add(int(raw))
        except Exception:
            continue
    return excluded

def _resolver_bool(step: ApprovalStep, key: str, default: bool = False) -> bool:
    rcfg: Dict[str, Any] = step.resolver_config or {}
    value = rcfg.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "có", "co"}
    return bool(value)


def _fallback_to_superuser_signers(request: ApprovalRequest, step: ApprovalStep, excluded_user_ids: set[int]) -> int:
    """
    Fallback có kiểm soát cho các môi trường đang cấu hình thiếu lãnh đạo.

    Mặc định KHÔNG dùng superuser làm người ký thay lãnh đạo đơn vị. Chỉ dùng khi
    resolver_config đặt rõ: fallback_to_superuser=True.
    """
    if not _resolver_bool(step, "fallback_to_superuser", False):
        return 0
    created = 0
    leaders = list(User.objects.filter(is_superuser=True, is_active=True).exclude(id__in=excluded_user_ids))
    for u in leaders:
        if not step.signers.filter(user_id=u.id).exists():
            ApprovalSigner.objects.create(
                step=step, user=u,
                role_title="SUPERUSER_FALLBACK", unit_id=request.unit_id,
                group_key="", source=ApprovalSigner.Source.RESOLVED,
            )
            created += 1
    return created


def _ensure_step_has_pending_signers(step: ApprovalStep) -> None:
    if not step.signers.filter(status=ApprovalSigner.Status.PENDING).exists():
        raise ValueError(
            f"Không xác định được người ký cho bước '{step.label or step.order_index}'. "
            "Vui lòng kiểm tra cấu hình luồng, Role Mapping, chức danh và user liên kết nhân sự."
        )


def _apply_attendance_correction_for_request(request: ApprovalRequest, actor: Optional[User] = None) -> Dict[str, Any]:
    """Áp dụng ACR và ghi audit lỗi theo một chỗ dùng chung cho auto-apply/retry."""
    apply_actor = actor or request.requester
    if not apply_correction_request:
        return {"ok": False, "error": "Thiếu service apply_correction_request"}
    if request.object_type != "attendance_correction":
        return {"ok": False, "error": "ApprovalRequest không phải phiếu sửa chấm công"}

    acr_id = None
    try:
        acr_id = int(request.object_id)
        result = apply_correction_request(acr_id=acr_id, actor=apply_actor)
        if not result or not result.get("ok"):
            audit_log(
                action_verb="APPLY_FAILED",
                object_type="attendance_correction",
                object_id=acr_id,
                object_repr=f"ApprovalRequest#{request.id}",
                actor=apply_actor,
                changes={"result": result or {}, "approval_request_id": request.id},
                severity="ERROR",
                action_code="ATT_CORRECTION_APPLY_FAILED",
            )
        return result or {"ok": False, "error": "Apply trả về kết quả rỗng"}
    except Exception as exc:
        audit_log(
            action_verb="APPLY_ERROR",
            object_type="attendance_correction",
            object_id=acr_id or request.object_id,
            object_repr=f"ApprovalRequest#{request.id}",
            actor=apply_actor,
            changes={"error": str(exc), "approval_request_id": request.id},
            severity="ERROR",
            action_code="ATT_CORRECTION_APPLY_ERROR",
        )
        return {"ok": False, "error": str(exc)}


def retry_apply_attendance_correction_request(request: ApprovalRequest, actor: Optional[User] = None) -> Dict[str, Any]:
    """Action thủ công cho trạng thái HR đã duyệt nhưng chưa áp dụng được vào công chốt."""
    if request.status != ApprovalRequest.Status.APPROVED:
        return {"ok": False, "error": "Phiếu phê duyệt chưa hoàn tất, không thể áp dụng lại."}
    return _apply_attendance_correction_for_request(request, actor=actor)


def _resolve_unit_leaders(request: ApprovalRequest, step: ApprovalStep) -> int:
    created = 0
    rcfg: Dict[str, Any] = step.resolver_config or {}
    use_req_unit: bool = bool(rcfg.get("use_requester_unit", False))
    static_units: List[int] = [int(x) for x in (rcfg.get("unit_ids") or []) if str(x).isdigit()]
    excluded_user_ids = _get_excluded_user_ids(request, step)

    unit_set = set(static_units)
    if use_req_unit and request.unit_id:
        unit_set.add(int(request.unit_id))

    if not unit_set or Employee is None:
        return _fallback_to_superuser_signers(request, step, excluded_user_ids)

    status_active = getattr(getattr(Employee, "Status", None), "ACTIVE", None)
    try:
        role_title_map = get_role_title_map() or JOB_TITLE_CODE_MAP
    except Exception:
        role_title_map = JOB_TITLE_CODE_MAP

    for uid in unit_set:
        if status_active is None:
            qs = Employee.objects.select_related("job_title").filter(unit_id=uid)
        else:
            qs = Employee.objects.select_related("job_title").filter(unit_id=uid, status=status_active)

        for emp in qs:
            jt_code = _get_employee_job_title_code(emp)
            if not jt_code:
                continue

            matched_role_title = None
            for role in ("HEAD", "DEPUTY", "IN_CHARGE"):
                if jt_code in role_title_map.get(role, set()):
                    matched_role_title = role
                    break
            if not matched_role_title:
                continue

            u = _get_employee_user(emp)
            if not u:
                continue
            if u.id in excluded_user_ids:
                continue

            if not step.signers.filter(user_id=u.id).exists():
                ApprovalSigner.objects.create(
                    step=step, user=u,
                    role_title=matched_role_title, unit_id=uid,
                    group_key="", source=ApprovalSigner.Source.RESOLVED,
                )
                created += 1

    if created == 0:
        created += _fallback_to_superuser_signers(request, step, excluded_user_ids)

    return created

def _step_quorum_satisfied(step: ApprovalStep) -> bool:
    if step.quorum == ApprovalStep.Quorum.ANY:
        return step.signers.filter(status=ApprovalSigner.Status.APPROVED).exists()
    if step.quorum == ApprovalStep.Quorum.ALL:
        total = step.signers.count()
        approved = step.signers.filter(status=ApprovalSigner.Status.APPROVED).count()
        return total > 0 and approved == total
    if step.quorum == ApprovalStep.Quorum.GROUP_ANY_ALL:
        groups = {}
        for s in step.signers.all():
            groups.setdefault(s.group_key or "__default__", []).append(s)
        for members in groups.values():
            if not any(m.status == ApprovalSigner.Status.APPROVED for m in members):
                return False
        return True
    return False

def activate_next_step_if_any(request: ApprovalRequest, actor: Optional[User] = None) -> None:
    """
    NEW: nếu yêu cầu đã CANCELLED -> không kích hoạt bước tiếp theo.
    """
    if request.status == ApprovalRequest.Status.CANCELLED:
        return

    nxt = request.steps.filter(status=ApprovalStep.Status.PENDING).order_by("order_index").first()
    if not nxt:
        request.status = ApprovalRequest.Status.APPROVED
        request.completed_at = timezone.now()
        request.save(update_fields=["status", "completed_at"])
        if request.object_type == "attendance_correction":
            _apply_attendance_correction_for_request(request, actor=actor or request.requester)
        return

    with transaction.atomic():
        # Khi đã kích hoạt được một bước ký, trạng thái vận hành của request phải là Đang xử lý.
        # Trước đây request thường giữ SUBMITTED đến tận cuối luồng nên UI dễ hiểu nhầm là mới gửi.
        if request.status in {ApprovalRequest.Status.DRAFT, ApprovalRequest.Status.SUBMITTED}:
            request.status = ApprovalRequest.Status.IN_PROGRESS
            request.save(update_fields=["status"])

        nxt.status = ApprovalStep.Status.ACTIVE
        nxt.activated_at = timezone.now()
        nxt.save(update_fields=["status", "activated_at"])

        rcfg: Dict[str, Any] = nxt.resolver_config or {}

        explicit_type_val = getattr(ApprovalStep.Type, "EXPLICIT_USERS", "EXPLICIT_USERS")
        unit_leaders_type_val = getattr(ApprovalStep.Type, "UNIT_LEADERS", "UNIT_LEADERS")
        dept_heads_type_val = getattr(ApprovalStep.Type, "DEPT_HEADS_FROM_EMPLOYEE_UNIT", "DEPT_HEADS_FROM_EMPLOYEE_UNIT")

        if nxt.type == explicit_type_val or str(nxt.type) == "EXPLICIT_USERS":
            user_ids = rcfg.get("user_ids", [])
            users = list(User.objects.filter(id__in=user_ids, is_active=True))
            for u in users:
                if not nxt.signers.filter(user_id=u.id).exists():
                    ApprovalSigner.objects.create(
                        step=nxt, user=u,
                        role_title="", unit_id=request.unit_id, group_key="",
                        source=ApprovalSigner.Source.EXPLICIT,
                    )

        elif nxt.type == unit_leaders_type_val or str(nxt.type) == "UNIT_LEADERS":
            _resolve_unit_leaders(request, nxt)

        elif nxt.type == dept_heads_type_val or str(nxt.type) == "DEPT_HEADS_FROM_EMPLOYEE_UNIT":
            _resolve_unit_leaders(request, nxt)

        _ensure_step_has_pending_signers(nxt)

        if Notification:
            try:
                signers = list(nxt.signers.select_related("user").filter(status=ApprovalSigner.Status.PENDING))
                for s in signers:
                    Notification.objects.create(
                        user=s.user,
                        title=f"Phê duyệt: {request.title}",
                        body=f"Bước '{nxt.label or 'Bước'}' đã kích hoạt. Vui lòng xem và xử lý.",
                        url=f"/backoffice/approvals/requests/{request.id}/",
                    )
            except Exception:
                pass

def approve_step(step: ApprovalStep, signer: ApprovalSigner, actor: User, comment: str = "") -> None:
    # NEW: chặn nếu request đã CANCELLED
    with transaction.atomic():
        step = ApprovalStep.objects.select_for_update().select_related("request").get(pk=step.pk)
        signer = ApprovalSigner.objects.select_for_update().get(pk=signer.pk)

        if step.request.status == ApprovalRequest.Status.CANCELLED:
            return
        if step.status != ApprovalStep.Status.ACTIVE or signer.status != ApprovalSigner.Status.PENDING:
            return

        signer.status = ApprovalSigner.Status.APPROVED
        signer.acted_at = timezone.now()
        signer.save(update_fields=["status", "acted_at"])

        ApprovalAction.objects.create(
            request=step.request, step=step, signer=signer, actor=actor,
            action=ApprovalAction.Action.APPROVE, comment=comment, meta_json={}
        )

        if _step_quorum_satisfied(step):
            step.status = ApprovalStep.Status.COMPLETED
            step.completed_at = timezone.now()
            step.save(update_fields=["status", "completed_at"])
            activate_next_step_if_any(step.request, actor=actor)

def reject_step(step: ApprovalStep, signer: ApprovalSigner, actor: User, reason: str) -> None:
    # NEW: chặn nếu request đã CANCELLED
    if step.request.status == ApprovalRequest.Status.CANCELLED:
        return
    if step.status != ApprovalStep.Status.ACTIVE or signer.status != ApprovalSigner.Status.PENDING:
        return

    signer.status = ApprovalSigner.Status.REJECTED
    signer.acted_at = timezone.now()
    signer.save(update_fields=["status", "acted_at"])

    step.status = ApprovalStep.Status.REJECTED
    step.completed_at = timezone.now()
    step.save(update_fields=["status", "completed_at"])

    ApprovalAction.objects.create(
        request=step.request, step=step, signer=signer, actor=actor,
        action=ApprovalAction.Action.REJECT, comment=reason, meta_json={}
    )

    req = step.request
    req.status = ApprovalRequest.Status.REJECTED
    req.completed_at = timezone.now()
    req.save(update_fields=["status", "completed_at"])