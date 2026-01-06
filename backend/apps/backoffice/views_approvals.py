from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.contrib import messages
from django.db.models import Q
from apps.approvals.models import ApprovalRequest, ApprovalStep, ApprovalSigner, ApprovalAction
from apps.approvals.services_runtime import approve_step, reject_step

# NEW: đồng bộ trạng thái ACR sau approve/reject
try:
    from apps.attendance.models_batch import AttendanceCorrectionRequest as ACR
except Exception:
    ACR = None

# NEW: lọc theo phạm vi đơn vị
try:
    from apps.hr.models import AccessControl
except Exception:
    AccessControl = None
try:
    from apps.organization.models import OrgUnit
    from apps.organization.utils import get_subtree_unit_ids
except Exception:
    OrgUnit = None
    def get_subtree_unit_ids(_): return []

def _unit_scope_ids(request):
    if not OrgUnit:
        return []
    base_qs = OrgUnit.objects.filter(is_attendance_unit=True, is_active=True)
    ac = getattr(request.user, "access_control", None)
    if not ac or (AccessControl and ac.scope == AccessControl.Scope.ALL_ORG):
        return list(base_qs.values_list("id", flat=True))
    root = getattr(ac, "root_org_unit", None)
    if not root:
        return []
    if AccessControl and ac.scope == AccessControl.Scope.UNIT_SUBTREE:
        return get_subtree_unit_ids(root)
    if AccessControl and ac.scope == AccessControl.Scope.PLANT_SUBTREE:
        plant = root
        while plant and getattr(plant, "type", None) != getattr(OrgUnit.Type, "PLANT", None):
            plant = plant.parent
        if not plant:
            return get_subtree_unit_ids(root)
        return get_subtree_unit_ids(plant)
    return list(base_qs.values_list("id", flat=True))

@login_required
def approvals_inbox(request):
    # scope: to_approve | my_requests | approved_by_me | in_units
    scope = request.GET.get("scope", "to_approve")
    q = request.GET.get("q", "").strip()

    data = []
    if scope == "my_requests":
        qs = ApprovalRequest.objects.select_related("flow", "flow_version", "requester").filter(
            requester_id=request.user.id
        ).order_by("-submitted_at", "-created_at")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(id__icontains=q))
        data = list(qs[:500])

    elif scope == "approved_by_me":
        signers = ApprovalSigner.objects.select_related("step__request", "step").filter(
            user_id=request.user.id, status=ApprovalSigner.Status.APPROVED
        ).order_by("-acted_at")[:500]
        data = [s.step.request for s in signers]

    elif scope == "in_units":
        unit_ids = _unit_scope_ids(request)
        qs = ApprovalRequest.objects.select_related("flow", "flow_version", "requester").filter(
            unit_id__in=unit_ids
        ).order_by("-submitted_at", "-created_at")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(id__icontains=q))
        data = list(qs[:500])

    else:  # to_approve
        signers = ApprovalSigner.objects.select_related("step__request", "step").filter(
            user_id=request.user.id,
            status=ApprovalSigner.Status.PENDING,
            step__status=ApprovalStep.Status.ACTIVE
        ).order_by("-step__activated_at")[:500]
        # NEW: không hiển thị yêu cầu đã CANCELLED trong "Tôi cần duyệt"
        data = [s.step.request for s in signers if s.step.request.status != ApprovalRequest.Status.CANCELLED]

    return render(request, "backoffice/approvals/inbox.html", {"requests": data, "scope": scope, "q": q})

@login_required
def approvals_my_requests(request):
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    qs = ApprovalRequest.objects.select_related("flow", "requester") \
        .filter(requester_id=request.user.id) \
        .order_by("-submitted_at", "-created_at")

    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(title__icontains=q) | qs.filter(id__icontains=q)

    requests_list = list(qs[:500])

    return render(request, "backoffice/approvals/my_requests.html", {"requests": requests_list, "status": status, "q": q})

@login_required
def approval_request_detail(request, request_id: int):
    req = get_object_or_404(ApprovalRequest.objects.select_related("flow", "flow_version", "requester"), pk=request_id)

    # Xác định quyền hành động: chỉ signer PENDING ở step ACTIVE mới có thể thao tác
    active_step = ApprovalStep.objects.filter(request=req, status=ApprovalStep.Status.ACTIVE).order_by("order_index").first()
    my_signer = None
    if active_step:
        my_signer = ApprovalSigner.objects.filter(step=active_step, user_id=request.user.id, status=ApprovalSigner.Status.PENDING).first()

    # Dựng danh sách bước + signer hiển thị
    steps_qs = ApprovalStep.objects.filter(request=req).order_by("order_index")
    steps = []
    for st in steps_qs:
        signers_qs = ApprovalSigner.objects.select_related("user").filter(step=st)
        signers = []
        for s in signers_qs:
            display_name = (getattr(s.user, "get_full_name", None) and s.user.get_full_name()) or \
                           (f"{getattr(s.user, 'last_name', '')} {getattr(s.user, 'first_name', '')}".strip()) or \
                           s.user.username
            last_action = ApprovalAction.objects.filter(step=st, signer=s).order_by("-created_at").first()
            comment = last_action.comment if last_action else ""
            signers.append({
                "display_name": display_name,
                "status_display": {
                    ApprovalSigner.Status.PENDING: _("Chờ ký"),
                    ApprovalSigner.Status.APPROVED: _("Đã phê duyệt"),
                    ApprovalSigner.Status.REJECTED: _("Đã từ chối"),
                    ApprovalSigner.Status.DELEGATED: _("Đã ủy quyền"),
                }.get(s.status, "—"),
                "comment": comment,
            })
        steps.append({
            "order_index": st.order_index,
            "label": st.label or _("Bước"),
            "status_display": {
                ApprovalStep.Status.PENDING: _("Chờ kích hoạt"),
                ApprovalStep.Status.ACTIVE: _("Đang ký"),
                ApprovalStep.Status.COMPLETED: _("Hoàn tất"),
                ApprovalStep.Status.REJECTED: _("Bị từ chối"),
            }.get(st.status, "—"),
            "signers": signers,
        })

    content_html = req.content_html or "<div class='text-muted'>Không có nội dung hiển thị.</div>"

    return render(request, "backoffice/approvals/request_detail.html", {
        "req": req,
        "steps": steps,
        "active_step": active_step,
        "my_signer": my_signer,
        "content_html": content_html,
    })

def _sync_acr_status_for_request(req: ApprovalRequest):
    """
    Đồng bộ trạng thái ACR theo trạng thái ApprovalRequest.
    - REJECTED -> ACR.Status.REJECTED
    - APPROVED -> ACR.Status.APPROVED_BY_HR
    - CANCELLED -> ACR.Status.CANCELLED
    Lưu ý: chỉ áp dụng cho object_type="attendance_correction".
    """
    if not ACR:
        return
    if req.object_type != "attendance_correction":
        return
    try:
        acr_id = int(req.object_id)
    except Exception:
        return
    acr = ACR.objects.filter(id=acr_id).first()
    if not acr:
        return
    try:
        if req.status == ApprovalRequest.Status.REJECTED:
            acr.status = getattr(ACR.Status, "REJECTED", "REJECTED")
            acr.save(update_fields=["status"])
        elif req.status == ApprovalRequest.Status.APPROVED:
            # Khi toàn bộ luồng đã APPROVED -> coi như đã duyệt xong bởi HR
            acr.status = getattr(ACR.Status, "APPROVED_BY_HR", "APPROVED_BY_HR")
            acr.save(update_fields=["status"])
        elif req.status == ApprovalRequest.Status.CANCELLED:
            acr.status = getattr(ACR.Status, "CANCELLED", "CANCELLED")
            acr.save(update_fields=["status"])
    except Exception:
        # tránh crash UI nếu đồng bộ thất bại
        pass

@login_required
def approval_step_action(request, request_id: int, order_index: int):
    req = get_object_or_404(ApprovalRequest, pk=request_id)
    step = get_object_or_404(ApprovalStep, request=req, order_index=order_index)

    # NEW: chặn thao tác nếu yêu cầu đã hủy
    if req.status == ApprovalRequest.Status.CANCELLED:
        messages.warning(request, _("Yêu cầu đã bị hủy, không thể thao tác."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    if step.status != ApprovalStep.Status.ACTIVE:
        messages.warning(request, _("Bước hiện tại không ở trạng thái Đang ký."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    signer = ApprovalSigner.objects.filter(step=step, user_id=request.user.id).first()
    if not signer or signer.status != ApprovalSigner.Status.PENDING:
        messages.warning(request, _("Bạn không phải người ký đang chờ ở bước này."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    if request.method != "POST":
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    action = request.POST.get("action", "").upper().strip()
    comment = request.POST.get("comment", "").strip()

    if action == "APPROVE":
        approve_step(step, signer, request.user, comment=comment or "")
        # Sau approve, trạng thái req có thể thay đổi (hoàn tất hoặc chuyển bước)
        req.refresh_from_db(fields=["status"])
        _sync_acr_status_for_request(req)
        messages.success(request, _("Đã phê duyệt bước thành công."))
    elif action == "REJECT":
        if not comment:
            messages.error(request, _("Vui lòng nhập lý do từ chối."))
            return redirect("backoffice:approvals_request_detail", request_id=req.id)
        reject_step(step, signer, request.user, reason=comment)
        # Sau reject, req.status phải là REJECTED -> đồng bộ ACR
        req.refresh_from_db(fields=["status"])
        _sync_acr_status_for_request(req)
        messages.success(request, _("Đã từ chối bước."))
    else:
        messages.error(request, _("Hành động không hợp lệ."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    return redirect("backoffice:approvals_request_detail", request_id=req.id)