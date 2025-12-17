from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError
from apps.approvals.models_config import RoleTitleMapping
from .forms_role_mapping import RoleTitleMappingForm
from apps.audit.utils import audit_log

@login_required
@permission_required("approvals.view_roletitlemapping", raise_exception=True)
def role_title_mapping_list(request):
    # Lấy tất cả bản ghi, sắp xếp rõ ràng
    items = RoleTitleMapping.objects.all().order_by("role_key", "title_code", "id")
    return render(request, "backoffice/approvals/role_mapping/list.html", {"items": items})

@login_required
@permission_required("approvals.add_roletitlemapping", raise_exception=True)
def role_title_mapping_create(request):
    if request.method == "POST":
        form = RoleTitleMappingForm(request.POST)
        if form.is_valid():
            try:
                obj = form.save()
                audit_log(
                    action_verb="CREATE",
                    object_type="role_title_mapping",
                    object_id=obj.id,
                    object_repr=f"{obj.role_key}:{obj.title_code}",
                    actor=request.user,
                    changes={"fields": {"role_key": obj.role_key, "title_code": obj.title_code, "is_active": obj.is_active}},
                    request=request,
                    action_code="ROLE_MAP_CREATE",
                )
                messages.success(request, "Đã thêm mapping.")
                return redirect("backoffice:role_title_mapping_list")
            except IntegrityError:
                form.add_error(None, "Mapping cho vai trò và chức danh này đã tồn tại.")
    else:
        form = RoleTitleMappingForm()
    return render(request, "backoffice/approvals/role_mapping/form.html", {"form": form, "create": True})

@login_required
@permission_required("approvals.change_roletitlemapping", raise_exception=True)
def role_title_mapping_edit(request, pk):
    obj = get_object_or_404(RoleTitleMapping, pk=pk)
    if request.method == "POST":
        old = {"role_key": obj.role_key, "title_code": obj.title_code, "is_active": obj.is_active}
        form = RoleTitleMappingForm(request.POST, instance=obj)
        if form.is_valid():
            try:
                updated = form.save()
                diff = {}
                for k, v in old.items():
                    nv = getattr(updated, k)
                    if v != nv:
                        diff[k] = {"old": v, "new": nv}
                if diff:
                    audit_log(
                        action_verb="UPDATE",
                        object_type="role_title_mapping",
                        object_id=updated.id,
                        object_repr=f"{updated.role_key}:{updated.title_code}",
                        actor=request.user,
                        changes=diff,
                        request=request,
                        action_code="ROLE_MAP_UPDATE",
                    )
                messages.success(request, "Đã cập nhật mapping.")
                return redirect("backoffice:role_title_mapping_list")
            except IntegrityError:
                form.add_error(None, "Mapping cho vai trò và chức danh này đã tồn tại.")
    else:
        form = RoleTitleMappingForm(instance=obj)
    return render(request, "backoffice/approvals/role_mapping/form.html", {"form": form, "obj": obj})

@login_required
@permission_required("approvals.delete_roletitlemapping", raise_exception=True)
def role_title_mapping_delete(request, pk):
    obj = get_object_or_404(RoleTitleMapping, pk=pk)
    if request.method == "POST":
        oid, reprs = obj.id, f"{obj.role_key}:{obj.title_code}"
        obj.delete()
        audit_log(
            action_verb="DELETE",
            object_type="role_title_mapping",
            object_id=oid,
            object_repr=reprs,
            actor=request.user,
            request=request,
            action_code="ROLE_MAP_DELETE",
        )
        messages.success(request, "Đã xóa mapping.")
        return redirect("backoffice:role_title_mapping_list")
    return render(request, "backoffice/approvals/role_mapping/confirm_delete.html", {"obj": obj})