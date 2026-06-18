from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.contrib import messages
from django.utils import timezone

from apps.approvals.models import ApprovalRequest, ApprovalStep, ApprovalSigner, ApprovalAction
from apps.audit.utils import audit_log

try:
    from apps.attendance.models_batch import AttendanceCorrectionRequest
except Exception:
    AttendanceCorrectionRequest = None


@login_required
def approval_request_cancel(request, request_id: int):
    """
    Cho phép requester hủy (cancel) yêu cầu phê duyệt khi chưa có ai duyệt.

    Guard:
      - Chỉ requester (người tạo) mới được hủy.
      - Không cho hủy nếu request đã APPROVED/REJECTED/CANCELLED.
      - Không cho hủy nếu đã có bất kỳ signer APPROVED.

    Hành động:
      - Tạo ApprovalAction với action=CANCEL, comment=reason.
      - Đặt status=CANCELLED, completed_at=now.
      - Audit log.
    """
    req = get_object_or_404(ApprovalRequest.objects.select_related("requester", "flow"), pk=request_id)

    # Quyền: chỉ requester mới được hủy
    if req.requester_id != request.user.id:
        messages.error(request, _("Bạn không phải người tạo yêu cầu này."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    # Trạng thái không cho hủy
    terminal_statuses = {
        ApprovalRequest.Status.APPROVED,
        ApprovalRequest.Status.REJECTED,
        ApprovalRequest.Status.CANCELLED,
    }
    if req.status in terminal_statuses:
        messages.warning(request, _("Yêu cầu đã ở trạng thái hoàn tất hoặc bị từ chối/hủy."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    # Không cho hủy nếu đã có bất kỳ phê duyệt
    already_approved = ApprovalSigner.objects.filter(step__request=req, status=ApprovalSigner.Status.APPROVED).exists()
    if already_approved:
        messages.error(request, _("Yêu cầu đã có phê duyệt, không thể hủy."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()
        # Cập nhật trạng thái
        req.status = ApprovalRequest.Status.CANCELLED
        req.completed_at = timezone.now()
        req.save(update_fields=["status", "completed_at"])

        # Đồng bộ trạng thái phiếu sửa công tương ứng để nháp không còn bị khóa.
        if AttendanceCorrectionRequest and req.object_type == "attendance_correction":
            try:
                acr = AttendanceCorrectionRequest.objects.filter(id=int(req.object_id)).first()
                if acr and acr.status != AttendanceCorrectionRequest.Status.APPLIED:
                    acr.status = AttendanceCorrectionRequest.Status.CANCELLED
                    acr.save(update_fields=["status"])
            except Exception:
                pass

        # Ghi hành động
        ApprovalAction.objects.create(
            request=req, step=None, signer=None, actor=request.user,
            action=ApprovalAction.Action.CANCEL,
            comment=reason, meta_json={}
        )

        # Audit
        audit_log(
            action_verb="CANCEL",
            object_type="approval_request",
            object_id=req.id,
            object_repr=f"{req.flow.flow_key}#{req.id}",
            actor=request.user,
            changes={"reason": reason},
            request=request,
            action_code="APP_REQ_CANCEL",
        )

        messages.success(request, _("Đã hủy yêu cầu phê duyệt."))
        return redirect("backoffice:approvals_my_requests")

    # GET -> confirm
    return render(request, "backoffice/approvals/request_confirm_cancel.html", {"req": req})