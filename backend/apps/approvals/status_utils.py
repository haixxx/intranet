from __future__ import annotations

from typing import Any, Optional

from .models import ApprovalAction, ApprovalRequest, ApprovalSigner, ApprovalStep

try:
    from apps.attendance.models_batch import AttendanceCorrectionRequest
except Exception:  # pragma: no cover - approvals vẫn hoạt động nếu app attendance chưa sẵn sàng
    AttendanceCorrectionRequest = None


BOOTSTRAP_BADGE_CLASS = {
    "success": "text-bg-success",
    "warning": "text-bg-warning",
    "danger": "text-bg-danger",
    "secondary": "text-bg-secondary",
    "info": "text-bg-info",
    "neutral": "text-bg-light text-dark",
}

BO_BADGE_CLASS = {
    "success": "bo-badge-success",
    "warning": "bo-badge-warning",
    "danger": "bo-badge-danger",
    "secondary": "bo-badge-secondary",
    "info": "bo-badge-info",
    "neutral": "bo-badge-secondary",
}


def _choice_label(model_or_choices: Any, value: str) -> str:
    if not value:
        return "—"
    try:
        choices = getattr(getattr(model_or_choices, "Status", None), "choices", None) or model_or_choices.choices
        return dict(choices).get(value, value)
    except Exception:
        return value


def _user_display(user) -> str:
    if not user:
        return "—"
    try:
        full_name = user.get_full_name()
    except Exception:
        full_name = ""
    return full_name or getattr(user, "username", "") or str(user)


def get_latest_acr_for_request(req: ApprovalRequest):
    """Lấy ACR tương ứng với ApprovalRequest sửa công, nếu có."""
    if AttendanceCorrectionRequest is None:
        return None
    if not req or req.object_type != "attendance_correction":
        return None
    try:
        return AttendanceCorrectionRequest.objects.filter(id=int(req.object_id)).first()
    except Exception:
        return None


def _active_step(req: ApprovalRequest) -> Optional[ApprovalStep]:
    try:
        return req.steps.filter(status=ApprovalStep.Status.ACTIVE).order_by("order_index").first()
    except Exception:
        return None


def _pending_signers_label(step: Optional[ApprovalStep], limit: int = 3) -> str:
    if not step:
        return ""
    names: list[str] = []
    try:
        qs = step.signers.select_related("user").filter(status=ApprovalSigner.Status.PENDING).order_by("id")
        total = qs.count()
        for signer in qs[:limit]:
            names.append(_user_display(signer.user))
        if total > limit:
            names.append(f"+{total - limit}")
    except Exception:
        return ""
    return ", ".join([x for x in names if x])


def _last_action_actor(req: ApprovalRequest, action: str = "APPROVE") -> str:
    try:
        act = (
            ApprovalAction.objects.select_related("actor")
            .filter(request=req, action=action)
            .order_by("-created_at")
            .first()
        )
        return _user_display(act.actor) if act else ""
    except Exception:
        return ""


def build_approval_status_context(req: ApprovalRequest, acr=None) -> dict[str, Any]:
    """
    Trạng thái vận hành dễ hiểu cho UI.

    Không chỉ in thô ApprovalRequest.status, vì với luồng sửa công trạng thái thật còn phụ thuộc:
      - bước đang active;
      - trạng thái ACR đã áp dụng hay mới HR duyệt;
      - dữ liệu cũ có thể còn SUBMITTED dù đã có bước ký active.
    """
    acr = acr if acr is not None else get_latest_acr_for_request(req)
    req_status = str(getattr(req, "status", "") or "")
    acr_status = str(getattr(acr, "status", "") or "") if acr else ""
    active = _active_step(req)
    active_label = (getattr(active, "label", "") or "").strip() if active else ""
    pending_signers = _pending_signers_label(active)

    category = "neutral"
    label = _choice_label(ApprovalRequest, req_status)
    note = ""

    if req_status == ApprovalRequest.Status.APPROVED:
        if acr and acr_status == getattr(AttendanceCorrectionRequest.Status, "APPLIED", "APPLIED"):
            label = "Đã áp dụng"
            category = "success"
            note = "Phiếu đã duyệt xong và thay đổi đã ghi vào công chốt."
        elif acr and acr_status == getattr(AttendanceCorrectionRequest.Status, "APPROVED_BY_HR", "APPROVED_BY_HR"):
            label = "HR đã duyệt / chờ áp dụng"
            category = "info"
            note = "Quy trình đã hoàn tất nhưng thay đổi chưa ghi vào công chốt; cần kiểm tra bước áp dụng hoặc audit lỗi apply."
        else:
            label = "Đã phê duyệt"
            category = "success"
            note = "Quy trình phê duyệt đã hoàn tất."
    elif req_status == ApprovalRequest.Status.REJECTED:
        label = "Đã từ chối"
        category = "danger"
        note = "Phiếu đã bị từ chối, không áp dụng thay đổi."
    elif req_status == ApprovalRequest.Status.CANCELLED:
        label = "Đã hủy"
        category = "secondary"
        note = "Người lập đã hủy phiếu; nháp có thể tiếp tục xử lý nếu không còn phiếu mở khác."
    elif active:
        label = f"Đang duyệt: {active_label or 'Bước hiện tại'}"
        category = "warning"
        if pending_signers:
            note = f"Đang chờ: {pending_signers}."
        else:
            note = "Bước hiện tại đang active nhưng chưa có người ký đang chờ; cần kiểm tra resolver/người ký."
    elif req_status == ApprovalRequest.Status.SUBMITTED:
        label = "Đã gửi / chờ kích hoạt"
        category = "warning"
        note = "Phiếu đã gửi nhưng chưa có bước ký active. Nếu kéo dài, cần kiểm tra cấu hình luồng."
    elif req_status == ApprovalRequest.Status.IN_PROGRESS:
        label = "Đang duyệt"
        category = "warning"
        note = "Phiếu đang trong quy trình duyệt."
    elif req_status == ApprovalRequest.Status.DRAFT:
        label = "Nháp"
        category = "neutral"

    # Ưu tiên cảnh báo ACR đã ở trạng thái cuối nếu lệch với request.
    if acr:
        if acr_status == getattr(AttendanceCorrectionRequest.Status, "APPLIED", "APPLIED"):
            label = "Đã áp dụng"
            category = "success"
            note = "Thay đổi đã ghi vào công chốt."
        elif acr_status == getattr(AttendanceCorrectionRequest.Status, "REJECTED", "REJECTED"):
            label = "Đã từ chối"
            category = "danger"
        elif acr_status == getattr(AttendanceCorrectionRequest.Status, "CANCELLED", "CANCELLED"):
            label = "Đã hủy"
            category = "secondary"
        elif acr_status == getattr(AttendanceCorrectionRequest.Status, "APPROVED_BY_HR", "APPROVED_BY_HR") and req_status != ApprovalRequest.Status.APPROVED:
            label = "HR đã duyệt / chờ áp dụng"
            category = "info"
            note = "ACR đang báo HR đã duyệt nhưng ApprovalRequest chưa hoàn tất; cần rà đồng bộ trạng thái."
        elif acr_status == getattr(AttendanceCorrectionRequest.Status, "APPROVED_BY_UNIT", "APPROVED_BY_UNIT") and active:
            label = f"Đơn vị đã duyệt / chờ {active_label or 'bước tiếp theo'}"
            category = "warning"
            if pending_signers:
                note = f"Đang chờ: {pending_signers}."

    return {
        "label": label,
        "category": category,
        "badge_class": BOOTSTRAP_BADGE_CLASS.get(category, BOOTSTRAP_BADGE_CLASS["neutral"]),
        "bo_badge_class": BO_BADGE_CLASS.get(category, BO_BADGE_CLASS["neutral"]),
        "note": note,
        "request_status": req_status,
        "request_status_label": _choice_label(ApprovalRequest, req_status),
        "acr_status": acr_status,
        "acr_status_label": _choice_label(AttendanceCorrectionRequest, acr_status) if acr and AttendanceCorrectionRequest else "—",
        "current_step_label": active_label or "—",
        "current_step_order": getattr(active, "order_index", None) if active else None,
        "pending_signers": pending_signers,
        "last_approver": _last_action_actor(req, ApprovalAction.Action.APPROVE),
        "is_waiting_apply": bool(acr and acr_status == getattr(AttendanceCorrectionRequest.Status, "APPROVED_BY_HR", "APPROVED_BY_HR")),
    }
