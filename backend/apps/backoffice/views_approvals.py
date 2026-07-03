from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from apps.approvals.models import ApprovalRequest, ApprovalStep, ApprovalSigner, ApprovalAction
from apps.approvals.services_runtime import approve_step, reject_step, retry_apply_attendance_correction_request
from apps.approvals.status_utils import build_approval_status_context
from .utils.pagination import paginate_queryset

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
    if getattr(request.user, "is_superuser", False):
        return list(base_qs.values_list("id", flat=True))

    ac = getattr(request.user, "access_control", None)
    if not ac:
        return []
    if AccessControl and ac.scope == AccessControl.Scope.ALL_ORG:
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
    return []


def _can_view_approval_request(request, req: ApprovalRequest) -> bool:
    """Guard xem chi tiết phiếu: requester, signer, superuser hoặc người có scope đơn vị."""
    user = request.user
    if getattr(user, "is_superuser", False):
        return True
    if req.requester_id == user.id:
        return True
    if ApprovalSigner.objects.filter(step__request=req, user_id=user.id).exists():
        return True
    if user.has_perm("approvals.view_approvalrequest"):
        if req.unit_id is None:
            return True
        return int(req.unit_id) in set(_unit_scope_ids(request))
    return False




def _can_retry_apply_correction(request, req: ApprovalRequest, status_ctx=None) -> bool:
    if getattr(request.user, "is_superuser", False):
        return bool(status_ctx and status_ctx.get("is_waiting_apply"))
    if not (status_ctx and status_ctx.get("is_waiting_apply")):
        return False
    return (
        request.user.has_perm("attendance.change_attendancecorrectionrequest")
        or request.user.has_perm("approvals.change_approvalrequest")
    )


def _unit_label(unit_id):
    if not unit_id or not OrgUnit:
        return "—"
    try:
        u = OrgUnit.objects.filter(id=unit_id).first()
        if not u:
            return str(unit_id)
        return getattr(u, "symbol", "") or getattr(u, "code", "") or getattr(u, "name", "") or str(unit_id)
    except Exception:
        return str(unit_id)


def _attach_status_context(items):
    for item in items:
        try:
            item.status_ctx = build_approval_status_context(item)
        except Exception:
            item.status_ctx = {
                "label": item.get_status_display(),
                "badge_class": "text-bg-light text-dark",
                "bo_badge_class": "bo-badge-secondary",
                "current_step_label": "—",
                "note": "",
            }
        item.unit_label = _unit_label(getattr(item, "unit_id", None))
    return items


def _filter_requests_q(qs, q: str):
    if not q:
        return qs
    cond = Q(title__icontains=q) | Q(object_id__icontains=q)
    if str(q).isdigit():
        cond |= Q(id=int(q))
    return qs.filter(cond)

@login_required
def approvals_inbox(request):
    # scope: to_approve | my_requests | approved_by_me | in_units
    scope = request.GET.get("scope", "to_approve")
    q = request.GET.get("q", "").strip()
    unit_id = request.GET.get("unit", "").strip()

    unit_scope_ids = _unit_scope_ids(request)
    unit_scope_set = set(unit_scope_ids)
    units_qs = OrgUnit.objects.filter(id__in=unit_scope_ids).order_by("symbol", "name") if OrgUnit else []

    context = {}
    if scope == "my_requests":
        qs = ApprovalRequest.objects.select_related("flow", "flow_version", "requester").filter(
            requester_id=request.user.id
        ).order_by("-submitted_at", "-created_at", "-id")
        if unit_id and unit_id.isdigit():
            qs = qs.filter(unit_id=int(unit_id))
        qs = _filter_requests_q(qs, q)
        context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
        data = list(context["items"])

    elif scope == "approved_by_me":
        signers_qs = ApprovalSigner.objects.select_related(
            "step__request", "step", "step__request__flow", "step__request__flow_version", "step__request__requester"
        ).filter(
            user_id=request.user.id, status=ApprovalSigner.Status.APPROVED
        ).order_by("-acted_at", "-id")
        if unit_id and unit_id.isdigit():
            signers_qs = signers_qs.filter(step__request__unit_id=int(unit_id))
        context = paginate_queryset(request, signers_qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
        data = [s.step.request for s in context["items"]]

    elif scope == "in_units":
        qs = ApprovalRequest.objects.select_related("flow", "flow_version", "requester").filter(
            unit_id__in=unit_scope_ids
        ).order_by("-submitted_at", "-created_at", "-id")
        if unit_id and unit_id.isdigit() and int(unit_id) in unit_scope_set:
            qs = qs.filter(unit_id=int(unit_id))
        qs = _filter_requests_q(qs, q)
        context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
        data = list(context["items"])

    else:  # to_approve
        signers_qs = ApprovalSigner.objects.select_related(
            "step__request", "step", "step__request__flow", "step__request__flow_version", "step__request__requester"
        ).filter(
            user_id=request.user.id,
            status=ApprovalSigner.Status.PENDING,
            step__status=ApprovalStep.Status.ACTIVE,
        ).exclude(
            step__request__status=ApprovalRequest.Status.CANCELLED
        ).order_by("-step__activated_at", "-id")
        if unit_id and unit_id.isdigit():
            signers_qs = signers_qs.filter(step__request__unit_id=int(unit_id))
        context = paginate_queryset(request, signers_qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
        data = [s.step.request for s in context["items"]]

    data = _attach_status_context(data)
    context.update({
        "requests": data,
        "scope": scope,
        "q": q,
        "unit_id": unit_id,
        "units_qs": units_qs,
    })
    return render(request, "backoffice/approvals/inbox.html", context)


@login_required
def approvals_my_requests(request):
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    qs = ApprovalRequest.objects.select_related("flow", "flow_version", "requester") \
        .filter(requester_id=request.user.id) \
        .order_by("-submitted_at", "-created_at", "-id")

    if status:
        qs = qs.filter(status=status)
    qs = _filter_requests_q(qs, q)

    context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    requests_list = _attach_status_context(list(context["items"]))
    context.update({"requests": requests_list, "status": status, "q": q})

    return render(request, "backoffice/approvals/my_requests.html", context)


@login_required
def approval_request_detail(request, request_id: int):
    req = get_object_or_404(ApprovalRequest.objects.select_related("flow", "flow_version", "requester"), pk=request_id)
    if not _can_view_approval_request(request, req):
        raise PermissionDenied(_("Bạn không có quyền xem yêu cầu phê duyệt này."))

    status_ctx = build_approval_status_context(req)
    unit_label = _unit_label(req.unit_id)
    can_retry_apply = _can_retry_apply_correction(request, req, status_ctx=status_ctx)

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
        for signer_obj in signers_qs:
            display_name = (getattr(signer_obj.user, "get_full_name", None) and signer_obj.user.get_full_name()) or \
                           (f"{getattr(signer_obj.user, 'last_name', '')} {getattr(signer_obj.user, 'first_name', '')}".strip()) or \
                           signer_obj.user.username
            last_action = ApprovalAction.objects.filter(step=st, signer=signer_obj).order_by("-created_at").first()
            comment = last_action.comment if last_action else ""
            signers.append({
                "display_name": display_name,
                "status_display": {
                    ApprovalSigner.Status.PENDING: _("Chờ ký"),
                    ApprovalSigner.Status.APPROVED: _("Đã phê duyệt"),
                    ApprovalSigner.Status.REJECTED: _("Đã từ chối"),
                    ApprovalSigner.Status.DELEGATED: _("Đã ủy quyền"),
                }.get(signer_obj.status, "—"),
                "status_class": {
                    ApprovalSigner.Status.PENDING: "text-bg-warning",
                    ApprovalSigner.Status.APPROVED: "text-bg-success",
                    ApprovalSigner.Status.REJECTED: "text-bg-danger",
                    ApprovalSigner.Status.DELEGATED: "text-bg-secondary",
                }.get(signer_obj.status, "text-bg-light text-dark"),
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
            "status_class": {
                ApprovalStep.Status.PENDING: "text-bg-light text-dark",
                ApprovalStep.Status.ACTIVE: "text-bg-warning",
                ApprovalStep.Status.COMPLETED: "text-bg-success",
                ApprovalStep.Status.REJECTED: "text-bg-danger",
            }.get(st.status, "text-bg-light text-dark"),
            "signers": signers,
        })

    actions = []
    for act in ApprovalAction.objects.select_related("actor", "step").filter(request=req).order_by("created_at"):
        actor_name = (getattr(act.actor, "get_full_name", None) and act.actor.get_full_name()) or getattr(act.actor, "username", "") or str(act.actor)
        actions.append({
            "created_at": act.created_at,
            "actor": actor_name,
            "action_display": {
                ApprovalAction.Action.SUBMIT: _("Gửi phê duyệt"),
                ApprovalAction.Action.APPROVE: _("Phê duyệt"),
                ApprovalAction.Action.REJECT: _("Từ chối"),
                ApprovalAction.Action.DELEGATE: _("Ủy quyền"),
                ApprovalAction.Action.COMMENT: _("Bình luận"),
                ApprovalAction.Action.CANCEL: _("Hủy yêu cầu"),
            }.get(act.action, act.action),
            "step_label": act.step.label if act.step else "—",
            "comment": act.comment,
        })

    content_html = req.content_html or "<div class='text-muted'>Không có nội dung hiển thị.</div>"

    return render(request, "backoffice/approvals/request_detail.html", {
        "req": req,
        "steps": steps,
        "actions": actions,
        "status_ctx": status_ctx,
        "unit_label": unit_label,
        "active_step": active_step,
        "my_signer": my_signer,
        "content_html": content_html,
        "can_retry_apply": can_retry_apply,
    })


@login_required
def approval_request_retry_apply(request, request_id: int):
    req = get_object_or_404(ApprovalRequest.objects.select_related("flow", "flow_version", "requester"), pk=request_id)
    if not _can_view_approval_request(request, req):
        raise PermissionDenied(_("Bạn không có quyền xem yêu cầu phê duyệt này."))

    status_ctx = build_approval_status_context(req)
    if not _can_retry_apply_correction(request, req, status_ctx=status_ctx):
        raise PermissionDenied(_("Bạn không có quyền áp dụng lại phiếu sửa công này."))

    if request.method != "POST":
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    result = retry_apply_attendance_correction_request(req, actor=request.user)
    _sync_acr_status_for_request(req)
    if result and result.get("ok"):
        messages.success(request, _("Đã áp dụng lại sửa công thành công."))
    else:
        messages.error(request, _("Chưa áp dụng được sửa công: %(error)s") % {"error": (result or {}).get("error") or (result or {})})
    return redirect("backoffice:approvals_request_detail", request_id=req.id)


def _sync_acr_status_for_request(req: ApprovalRequest):
    """
    Đồng bộ trạng thái ACR theo trạng thái ApprovalRequest và tiến độ bước duyệt.
    - REJECTED -> ACR.REJECTED
    - CANCELLED -> ACR.CANCELLED
    - APPROVED + apply thành công -> ACR.APPLIED do service apply cập nhật
    - APPROVED + apply lỗi/chưa chạy -> ACR.APPROVED_BY_HR
    - Bước 1 hoàn tất, bước HR đang chờ -> ACR.APPROVED_BY_UNIT
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
        applied_status = getattr(ACR.Status, "APPLIED", "APPLIED")
        # APPLIED là trạng thái cuối cao nhất: không ghi ngược về APPROVED_BY_HR/REJECTED/CANCELLED.
        if acr.status == applied_status:
            return

        if req.status == ApprovalRequest.Status.REJECTED:
            acr.status = getattr(ACR.Status, "REJECTED", "REJECTED")
            acr.save(update_fields=["status"])
        elif req.status == ApprovalRequest.Status.APPROVED:
            acr.status = getattr(ACR.Status, "APPROVED_BY_HR", "APPROVED_BY_HR")
            last_approve = ApprovalAction.objects.filter(request=req, action=ApprovalAction.Action.APPROVE).order_by("-created_at").first()
            if last_approve:
                acr.approved_hr_by = last_approve.actor
                acr.approved_hr_at = last_approve.created_at
                acr.save(update_fields=["status", "approved_hr_by", "approved_hr_at"])
            else:
                acr.save(update_fields=["status"])
        elif req.status == ApprovalRequest.Status.CANCELLED:
            acr.status = getattr(ACR.Status, "CANCELLED", "CANCELLED")
            acr.save(update_fields=["status"])
        else:
            first_step = req.steps.order_by("order_index").first()
            if first_step and first_step.status == ApprovalStep.Status.COMPLETED and acr.status == getattr(ACR.Status, "REQUESTED", "REQUESTED"):
                acr.status = getattr(ACR.Status, "APPROVED_BY_UNIT", "APPROVED_BY_UNIT")
                first_approve = ApprovalAction.objects.filter(request=req, step=first_step, action=ApprovalAction.Action.APPROVE).order_by("-created_at").first()
                if first_approve:
                    acr.approved_unit_by = first_approve.actor
                    acr.approved_unit_at = first_approve.created_at
                    acr.save(update_fields=["status", "approved_unit_by", "approved_unit_at"])
                else:
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
        try:
            approve_step(step, signer, request.user, comment=comment or "")
        except Exception as exc:
            messages.error(request, _("Không thể phê duyệt bước này: %(error)s") % {"error": str(exc)})
            return redirect("backoffice:approvals_request_detail", request_id=req.id)
        # Sau approve, trạng thái req có thể thay đổi (hoàn tất hoặc chuyển bước)
        req.refresh_from_db(fields=["status"])
        _sync_acr_status_for_request(req)
        messages.success(request, _("Đã phê duyệt bước thành công."))
    elif action == "REJECT":
        if not comment:
            messages.error(request, _("Vui lòng nhập lý do từ chối."))
            return redirect("backoffice:approvals_request_detail", request_id=req.id)
        try:
            reject_step(step, signer, request.user, reason=comment)
        except Exception as exc:
            messages.error(request, _("Không thể từ chối bước này: %(error)s") % {"error": str(exc)})
            return redirect("backoffice:approvals_request_detail", request_id=req.id)
        # Sau reject, req.status phải là REJECTED -> đồng bộ ACR
        req.refresh_from_db(fields=["status"])
        _sync_acr_status_for_request(req)
        messages.success(request, _("Đã từ chối bước."))
    else:
        messages.error(request, _("Hành động không hợp lệ."))
        return redirect("backoffice:approvals_request_detail", request_id=req.id)

    return redirect("backoffice:approvals_request_detail", request_id=req.id)
