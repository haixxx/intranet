from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.approvals.models import ApprovalFlow, ApprovalFlowVersion
from .forms_approvals_flow import ApprovalFlowForm
from .forms_approvals_builder import ApprovalFlowVersionBuilderForm
from apps.audit.utils import audit_log
from .utils.pagination import paginate_queryset
try:
    from apps.organization.models import OrgUnit
except Exception:
    OrgUnit = None

User = get_user_model()

# FLOW

@login_required
@permission_required("approvals.view_approvalflow", raise_exception=True)
def flow_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    qs = ApprovalFlow.objects.order_by("flow_key", "id")
    if q:
        qs = qs.filter(Q(flow_key__icontains=q) | Q(name__icontains=q) | Q(description__icontains=q))
    if status:
        qs = qs.filter(status=status)
    context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    context.update({"query": q, "status_selected": status, "status_choices": ApprovalFlow.Status.choices})
    return render(request, "backoffice/approvals/admin/flow_list.html", context)

@login_required
@permission_required("approvals.add_approvalflow", raise_exception=True)
def flow_create(request):
    if request.method == "POST":
        form = ApprovalFlowForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, "Đã tạo luồng.")
            audit_log(
                action_verb="CREATE",
                object_type="approval_flow",
                object_id=obj.id,
                object_repr=obj.flow_key,
                actor=request.user,
                changes={"fields": {"name": obj.name}},
                request=request,
                action_code="APP_FLOW_CREATE",
            )
            return redirect("backoffice:approval_flow_list")
    else:
        form = ApprovalFlowForm()
    return render(request, "backoffice/approvals/admin/flow_form.html", {"form": form, "create": True})

@login_required
@permission_required("approvals.change_approvalflow", raise_exception=True)
def flow_edit(request, flow_id: int):
    obj = get_object_or_404(ApprovalFlow, pk=flow_id)
    if request.method == "POST":
        old = {
            "name": obj.name,
            "description": obj.description,
            "status": obj.status,
            "settings_json": obj.settings_json,
        }
        form = ApprovalFlowForm(request.POST, instance=obj)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {"old": v, "new": nv}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="approval_flow",
                    object_id=updated.id,
                    object_repr=updated.flow_key,
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="APP_FLOW_UPDATE",
                )
            messages.success(request, "Đã cập nhật luồng.")
            return redirect("backoffice:approval_flow_list")
    else:
        form = ApprovalFlowForm(instance=obj)
    return render(request, "backoffice/approvals/admin/flow_form.html", {"form": form, "obj": obj})

@login_required
@permission_required("approvals.delete_approvalflow", raise_exception=True)
def flow_delete(request, flow_id: int):
    obj = get_object_or_404(ApprovalFlow, pk=flow_id)
    if request.method == "POST":
        oid = obj.id
        key = obj.flow_key
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, "Không thể xóa luồng vì đã phát sinh yêu cầu phê duyệt hoặc dữ liệu liên quan.")
            return redirect("backoffice:approval_flow_list")
        audit_log(
            action_verb="DELETE",
            object_type="approval_flow",
            object_id=oid,
            object_repr=key,
            actor=request.user,
            changes={},
            request=request,
            action_code="APP_FLOW_DELETE",
        )
        messages.success(request, "Đã xóa luồng.")
        return redirect("backoffice:approval_flow_list")
    return render(request, "backoffice/approvals/admin/flow_confirm_delete.html", {"obj": obj})

# VERSION (Builder-only)
def _users_for_popup():
    # Lấy danh sách user ACTIVE cho popup chọn người ký
    return User.objects.filter(is_active=True).order_by("username")

@login_required
@permission_required("approvals.view_approvalflowversion", raise_exception=True)
def version_list(request, flow_id: int):
    flow = get_object_or_404(ApprovalFlow, pk=flow_id)
    qs = flow.versions.order_by("-version", "-id")
    context = paginate_queryset(request, qs, default_page_size=25, allowed_page_sizes=(25, 50, 100, 200))
    context.update({"flow": flow})
    return render(request, "backoffice/approvals/admin/version_list.html", context)

@login_required
@permission_required("approvals.add_approvalflowversion", raise_exception=True)
def version_create_builder(request, flow_id: int):
    flow = get_object_or_404(ApprovalFlow, pk=flow_id)
    units_qs = OrgUnit.objects.filter(is_active=True).order_by("name") if OrgUnit else []
    users_qs = _users_for_popup()
    initial_steps = []
    if request.method == "POST":
        form = ApprovalFlowVersionBuilderForm(request.POST)
        raw_steps = _collect_raw_steps_from_post(request)
        initial_steps = _steps_for_builder_render(raw_steps)
        if form.is_valid():
            version_number = form.cleaned_data.get("version") or _next_version(flow)
            if flow.versions.filter(version=version_number).exists():
                form.add_error("version", f"Phiên bản {version_number} đã tồn tại trong luồng này.")
            else:
                try:
                    steps_json = form.build_steps_json(raw_steps)
                except Exception as e:
                    form.add_error(None, str(e))
                else:
                    with transaction.atomic():
                        ver = ApprovalFlowVersion(
                            flow=flow,
                            version=version_number,
                            steps_json=steps_json,
                            is_active=bool(form.cleaned_data.get("is_active")),
                            notes=form.cleaned_data.get("notes") or "",
                        )
                        ver.save()
                        audit_log(
                            action_verb="CREATE",
                            object_type="approval_flow_version",
                            object_id=ver.id,
                            object_repr=f"{flow.flow_key} v{ver.version}",
                            actor=request.user,
                            changes={"fields": {"version": ver.version}},
                            request=request,
                            action_code="APP_FLOW_VER_CREATE_BUILDER",
                        )
                        messages.success(request, "Đã tạo phiên bản (Builder).")
                        return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
    else:
        form = ApprovalFlowVersionBuilderForm()
    return render(
        request,
        "backoffice/approvals/admin/version_form_builder.html",
        {"flow": flow, "form": form, "create": True, "initial_steps": initial_steps, "units_qs": units_qs, "users_qs": users_qs}
    )

@login_required
@permission_required("approvals.change_approvalflowversion", raise_exception=True)
def version_edit_builder(request, flow_id: int, version_id: int):
    flow = get_object_or_404(ApprovalFlow, pk=flow_id)
    ver = get_object_or_404(ApprovalFlowVersion, pk=version_id, flow=flow)
    units_qs = OrgUnit.objects.filter(is_active=True).order_by("name") if OrgUnit else []
    users_qs = _users_for_popup()

    # CHUYỂN các bước kiểu cũ sang dạng mới để render/sửa trên builder
    raw_steps = ver.steps_json or []
    initial_steps = []
    for st in raw_steps:
        s = dict(st)
        if s.get("type") == "DEPT_HEADS_FROM_EMPLOYEE_UNIT":
            s["type"] = "UNIT_LEADERS"
            if s.get("quorum") == "GROUP_ANY_ALL":
                s["quorum"] = "ANY"
            s["resolver"] = {
                "use_requester_unit": True,
                "unit_ids": []
            }
        initial_steps.append(s)

    if request.method == "POST":
        form = ApprovalFlowVersionBuilderForm(request.POST)
        post_steps = _collect_raw_steps_from_post(request)
        initial_steps = _steps_for_builder_render(post_steps)
        if form.is_valid():
            version_number = form.cleaned_data.get("version") or ver.version
            if flow.versions.filter(version=version_number).exclude(pk=ver.pk).exists():
                form.add_error("version", f"Phiên bản {version_number} đã tồn tại trong luồng này.")
            else:
                try:
                    steps_json = form.build_steps_json(post_steps)
                except Exception as e:
                    form.add_error(None, str(e))
                else:
                    with transaction.atomic():
                        old_version = ver.version
                        ver.version = version_number
                        ver.is_active = bool(form.cleaned_data.get("is_active"))
                        ver.notes = form.cleaned_data.get("notes") or ""
                        ver.steps_json = steps_json
                        ver.save()
                        if flow.current_version == old_version and old_version != ver.version:
                            flow.current_version = ver.version
                            flow.save(update_fields=["current_version"])
                        audit_log(
                            action_verb="UPDATE",
                            object_type="approval_flow_version",
                            object_id=ver.id,
                            object_repr=f"{flow.flow_key} v{ver.version}",
                            actor=request.user,
                            changes={"changed": True},
                            request=request,
                            action_code="APP_FLOW_VER_UPDATE_BUILDER",
                        )
                        messages.success(request, "Đã cập nhật phiên bản (Builder).")
                        return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
    else:
        form = ApprovalFlowVersionBuilderForm(initial={
            "version": ver.version,
            "is_active": ver.is_active,
            "notes": ver.notes,
            "steps_count": len(initial_steps),
        })
    return render(
        request,
        "backoffice/approvals/admin/version_form_builder.html",
        {"flow": flow, "form": form, "obj": ver, "initial_steps": initial_steps, "units_qs": units_qs, "users_qs": users_qs}
    )

@login_required
@permission_required("approvals.change_approvalflow", raise_exception=True)
def version_publish(request, flow_id: int, version_id: int):
    flow = get_object_or_404(ApprovalFlow, pk=flow_id)
    ver = get_object_or_404(ApprovalFlowVersion, pk=version_id, flow=flow)
    if request.method == "POST":
        with transaction.atomic():
            flow.current_version = ver.version
            flow.status = ApprovalFlow.Status.PUBLISHED
            flow.save(update_fields=["current_version", "status"])
            flow.versions.exclude(pk=ver.pk).update(is_active=False)
            ver.is_active = True
            ver.published_at = timezone.now()
            ver.published_by = request.user
            ver.save(update_fields=["is_active", "published_at", "published_by"])
            audit_log(
                action_verb="UPDATE",
                object_type="approval_flow_publish",
                object_id=flow.id,
                object_repr=flow.flow_key,
                actor=request.user,
                changes={"current_version": ver.version},
                request=request,
                action_code="APP_FLOW_PUBLISH",
            )
            messages.success(request, f"Đã publish v{ver.version} cho {flow.flow_key}.")
            return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
    return render(request, "backoffice/approvals/admin/version_confirm_publish.html", {"flow": flow, "obj": ver})

@login_required
@permission_required("approvals.delete_approvalflowversion", raise_exception=True)
def version_delete(request, flow_id: int, version_id: int):
    flow = get_object_or_404(ApprovalFlow, pk=flow_id)
    ver = get_object_or_404(ApprovalFlowVersion, pk=version_id, flow=flow)
    if request.method == "POST":
        if flow.current_version == ver.version:
            messages.error(request, "Không thể xóa phiên bản hiện hành. Hãy publish phiên bản khác trước khi xóa.")
            return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
        oid = ver.id
        try:
            ver.delete()
        except ProtectedError:
            messages.error(request, "Không thể xóa phiên bản vì đã có yêu cầu phê duyệt sử dụng phiên bản này.")
            return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
        audit_log(
            action_verb="DELETE",
            object_type="approval_flow_version",
            object_id=oid,
            object_repr=f"{flow.flow_key}",
            actor=request.user,
            changes={},
            request=request,
            action_code="APP_FLOW_VER_DELETE",
        )
        messages.success(request, "Đã xóa phiên bản.")
        return redirect("backoffice:approval_flow_version_list", flow_id=flow.id)
    return render(request, "backoffice/approvals/admin/version_confirm_delete.html", {"flow": flow, "obj": ver})


def _steps_for_builder_render(raw_steps: list) -> list:
    """Convert POST-shaped builder steps back to template-shaped steps after validation errors."""
    rendered = []
    for raw in raw_steps or []:
        step_type = raw.get("type") or "EXPLICIT_USERS"
        user_ids = []
        for item in str(raw.get("user_ids") or "").split(","):
            item = item.strip()
            if item:
                user_ids.append(item)
        unit_id = raw.get("unit_id")
        rendered.append({
            "order": raw.get("order") or len(rendered) + 1,
            "type": step_type,
            "label": raw.get("label") or "",
            "quorum": raw.get("quorum") or "ALL",
            "allow_overrides": bool(raw.get("allow_overrides")),
            "resolver": {
                "user_ids": user_ids,
                "use_requester_unit": bool(raw.get("use_requester_unit")),
                "unit_ids": ([unit_id] if unit_id else []),
            },
        })
    return rendered

def _next_version(flow: ApprovalFlow) -> int:
    last = flow.versions.order_by("-version").first()
    return (last.version + 1) if last else 1

def _collect_raw_steps_from_post(request) -> list:
    """
    Thu thập dữ liệu các bước từ POST.
    Builder gửi mỗi bước với prefix step_<index>_<field>.
    Lưu ý:
      - unit_id là single select (một đơn vị).
    """
    steps = {}
    for k in request.POST.keys():
        if not k.startswith("step_"):
            continue
        parts = k.split("_", 2)
        if len(parts) != 3:
            continue
        _, idx, field = parts
        try:
            idx_int = int(idx)
        except Exception:
            continue
        step = steps.get(idx_int, {})
        step[field] = request.POST.get(k)
        steps[idx_int] = step

    raw_list = [steps[i] for i in sorted(steps.keys())]
    # Chuẩn hoá boolean
    for s in raw_list:
        for fld in ["allow_overrides", "use_requester_unit"]:
            s[fld] = True if s.get(fld) in {"on", "true", "True", "1"} else False
    # Chuẩn hoá order sang int
    for s in raw_list:
        try:
            s["order"] = int(s.get("order") or 0)
        except Exception:
            s["order"] = 0
    # Chuẩn hoá unit_id sang int nếu có
    for s in raw_list:
        uid = s.get("unit_id")
        if uid and str(uid).isdigit():
            s["unit_id"] = int(uid)
        else:
            s["unit_id"] = None
    return raw_list