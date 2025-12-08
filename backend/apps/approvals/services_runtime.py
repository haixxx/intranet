from typing import Dict, Any, List
from django.utils import timezone
from django.db import transaction
from django.utils.translation import gettext as _
from django.contrib.auth import get_user_model
from .models import (
    ApprovalRequest, ApprovalStep, ApprovalSigner, ApprovalAction
)
from .services_resolvers import resolve_dept_heads_of_employee_unit, resolve_explicit_users

User = get_user_model()


def activate_next_step_if_any(request: ApprovalRequest) -> None:
    nxt = request.steps.filter(status=ApprovalStep.Status.PENDING).order_by("order_index").first()
    if not nxt:
        # hoàn tất request
        request.status = ApprovalRequest.Status.APPROVED
        request.completed_at = timezone.now()
        request.save(update_fields=["status", "completed_at"])
        return

    with transaction.atomic():
        nxt.status = ApprovalStep.Status.ACTIVE
        nxt.activated_at = timezone.now()
        nxt.save(update_fields=["status", "activated_at"])

        # resolve signers theo type
        rcfg = nxt.resolver_config or {}

        if nxt.type == ApprovalStep.Type.DEPT_HEADS_FROM_EMPLOYEE_UNIT:
            # yêu cầu metadata_json chứa employee_user_id của NSTK
            employee_user_id = int(request.metadata_json.get("employee_user_id", 0))
            role_chain = rcfg.get("role_chain", ["HEAD", "DEPUTY", "IN_CHARGE"])
            signers = resolve_dept_heads_of_employee_unit(employee_user_id, role_chain)
            for user, meta in signers:
                ApprovalSigner.objects.create(
                    step=nxt, user=user,
                    role_title=meta.get("role_title", ""),
                    unit_id=request.unit_id,
                    group_key=meta.get("group_key", ""),
                    source=ApprovalSigner.Source.RESOLVED,
                )

        elif nxt.type == ApprovalStep.Type.EXPLICIT_USERS:
            user_ids = rcfg.get("user_ids", [])
            signers = resolve_explicit_users(user_ids)
            for user, meta in signers:
                ApprovalSigner.objects.create(
                    step=nxt, user=user,
                    role_title=meta.get("role_title", ""),
                    unit_id=request.unit_id,
                    group_key=meta.get("group_key", ""),
                    source=ApprovalSigner.Source.EXPLICIT,
                )

        else:
            # các type khác sẽ bổ sung sau
            pass


def submit_request(request: ApprovalRequest, actor: User) -> None:
    # Chuyển sang SUBMITTED (nếu đang nháp), rồi kích hoạt bước đầu
    if request.status == ApprovalRequest.Status.DRAFT:
        request.status = ApprovalRequest.Status.SUBMITTED
        request.submitted_at = timezone.now()
        request.save(update_fields=["status", "submitted_at"])

    ApprovalAction.objects.create(
        request=request, step=None, signer=None, actor=actor,
        action=ApprovalAction.Action.SUBMIT, comment="", meta_json={}
    )
    activate_next_step_if_any(request)


def _step_quorum_satisfied(step: ApprovalStep) -> bool:
    # Quorum cho flow sửa chấm công:
    # - Bước 1: GROUP_ANY_ALL (thực tế 1 nhóm đơn vị → ANY 1 người là đủ)
    # - Bước 2: ALL (HR đích danh phải ký)
    if step.quorum == ApprovalStep.Quorum.ANY:
        return step.signers.filter(status=ApprovalSigner.Status.APPROVED).exists()
    elif step.quorum == ApprovalStep.Quorum.ALL:
        total = step.signers.count()
        approved = step.signers.filter(status=ApprovalSigner.Status.APPROVED).count()
        return total > 0 and approved == total
    elif step.quorum == ApprovalStep.Quorum.GROUP_ANY_ALL:
        # Tính theo group_key: mỗi group cần >=1 APPROVED
        groups = {}
        for s in step.signers.all():
            groups.setdefault(s.group_key or "__default__", []).append(s)
        for gkey, members in groups.items():
            if not any(m.status == ApprovalSigner.Status.APPROVED for m in members):
                return False
        return True
    return False


def approve_step(step: ApprovalStep, signer: ApprovalSigner, actor: User, comment: str = "") -> None:
    if step.status != ApprovalStep.Status.ACTIVE:
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
        # kích hoạt bước tiếp theo
        activate_next_step_if_any(step.request)


def reject_step(step: ApprovalStep, signer: ApprovalSigner, actor: User, reason: str) -> None:
    if step.status != ApprovalStep.Status.ACTIVE:
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

    # Chính sách: REJECT_IMMEDIATE
    req = step.request
    req.status = ApprovalRequest.Status.REJECTED
    req.completed_at = timezone.now()
    req.save(update_fields=["status", "completed_at"])