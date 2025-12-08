from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils.translation import gettext as _
from django.db.models import Q

from .models import ApprovalRequest, ApprovalStep, ApprovalSigner
from .services_runtime import approve_step, reject_step


@login_required
def approvals_inbox(request):
    """
    Danh sách phê duyệt: Tôi phải phê duyệt (pending/active).
    """
    signers = ApprovalSigner.objects.select_related("step", "step__request").filter(
        user=request.user,
        status=ApprovalSigner.Status.PENDING,
        step__status=ApprovalStep.Status.ACTIVE
    ).order_by("-step__activated_at")

    return render(request, "approvals/inbox.html", {"signers": signers})


@login_required
def approvals_my_requests(request):
    """
    Danh sách yêu cầu do tôi lập (SUBMITTED/IN_PROGRESS/APPROVED/REJECTED).
    """
    qs = ApprovalRequest.objects.filter(requester=request.user).order_by("-submitted_at", "-created_at")
    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(object_id__icontains=q))
    return render(request, "approvals/my_requests.html", {"requests": qs, "status": status, "q": q})


@login_required
def approval_request_detail(request, request_id: int):
    """
    Chi tiết yêu cầu: metadata, timeline bước, người ký, trạng thái.
    """
    req = get_object_or_404(ApprovalRequest.objects.select_related("flow", "flow_version", "requester"), pk=request_id)
    steps = req.steps.select_related().prefetch_related("signers", "actions").order_by("order_index")
    return render(request, "approvals/request_detail.html", {"req": req, "steps": steps})


@login_required
def approval_action_approve(request, request_id: int, step_id: int, signer_id: int):
    req = get_object_or_404(ApprovalRequest, pk=request_id)
    step = get_object_or_404(ApprovalStep, pk=step_id, request=req)
    signer = get_object_or_404(ApprovalSigner, pk=signer_id, step=step, user=request.user)

    if step.status != ApprovalStep.Status.ACTIVE or signer.status != ApprovalSigner.Status.PENDING:
        messages.warning(request, _("Bước này không ở trạng thái có thể ký."))
        return redirect("approvals:request_detail", request_id=req.id)

    approve_step(step, signer, request.user, comment=request.POST.get("comment", "").strip())
    messages.success(request, _("Đã phê duyệt bước."))
    return redirect("approvals:request_detail", request_id=req.id)


@login_required
def approval_action_reject(request, request_id: int, step_id: int, signer_id: int):
    req = get_object_or_404(ApprovalRequest, pk=request_id)
    step = get_object_or_404(ApprovalStep, pk=step_id, request=req)
    signer = get_object_or_404(ApprovalSigner, pk=signer_id, step=step, user=request.user)

    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, _("Vui lòng nhập lý do từ chối."))
        return redirect("approvals:request_detail", request_id=req.id)

    if step.status != ApprovalStep.Status.ACTIVE or signer.status != ApprovalSigner.Status.PENDING:
        messages.warning(request, _("Bước này không ở trạng thái có thể từ chối."))
        return redirect("approvals:request_detail", request_id=req.id)

    reject_step(step, signer, request.user, reason=reason)
    messages.success(request, _("Đã từ chối yêu cầu."))
    return redirect("approvals:request_detail", request_id=req.id)