from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.utils import audit_log
from apps.organization.forms import ShiftTemplateForm
from apps.organization.models import ShiftTemplate


@login_required
@permission_required("organization.view_shifttemplate", raise_exception=True)
def shift_list(request):
    items = ShiftTemplate.objects.order_by("is_active", "code")
    return render(request, "backoffice/org/shifts/list.html", {"items": items})


@login_required
@permission_required("organization.add_shifttemplate", raise_exception=True)
def shift_create(request):
    if request.method == "POST":
        form = ShiftTemplateForm(request.POST)
        if form.is_valid():
            obj = form.save()
            audit_log(
                action_verb="CREATE",
                object_type="shift",
                object_id=obj.id,
                object_repr=obj.code,
                actor=request.user,
                changes={"fields": {"code": obj.code, "type": obj.type}},
                request=request,
                action_code="SHIFT_TEMPLATE_CREATE",
            )
            messages.success(request, "Đã tạo ca làm việc.")
            return redirect("backoffice:shift_list")
    else:
        form = ShiftTemplateForm()
    return render(request, "backoffice/org/shifts/form.html", {"form": form, "create": True})


@login_required
@permission_required("organization.change_shifttemplate", raise_exception=True)
def shift_edit(request, pk):
    obj = get_object_or_404(ShiftTemplate, pk=pk)
    if request.method == "POST":
        old = {
            "name": obj.name,
            "type": obj.type,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "breaks": obj.breaks,
            "crosses_midnight": obj.crosses_midnight,
            "is_active": obj.is_active,
        }
        form = ShiftTemplateForm(request.POST, instance=obj)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {"old": str(v), "new": str(nv)}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="shift",
                    object_id=updated.id,
                    object_repr=updated.code,
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="SHIFT_TEMPLATE_UPDATE",
                )
            messages.success(request, "Đã cập nhật ca làm việc.")
            return redirect("backoffice:shift_list")
    else:
        form = ShiftTemplateForm(instance=obj)
    return render(request, "backoffice/org/shifts/form.html", {"form": form, "obj": obj})


@login_required
@permission_required("organization.delete_shifttemplate", raise_exception=True)
def shift_delete(request, pk):
    obj = get_object_or_404(ShiftTemplate, pk=pk)

    if request.method == "POST":
        oid, code = obj.id, obj.code
        try:
            obj.delete()
        except ProtectedError:
            obj.is_active = False
            obj.save(update_fields=["is_active"])
            audit_log(
                action_verb="UPDATE",
                object_type="shift",
                object_id=oid,
                object_repr=code,
                actor=request.user,
                changes={"is_active": {"old": True, "new": False}},
                request=request,
                action_code="SHIFT_TEMPLATE_DEACTIVATE_INSTEAD_OF_DELETE",
            )
            messages.warning(
                request,
                "Ca làm việc đang có dữ liệu liên kết nên không xóa trực tiếp. Đã chuyển sang trạng thái ngừng hoạt động.",
            )
            return redirect("backoffice:shift_list")

        audit_log(
            action_verb="DELETE",
            object_type="shift",
            object_id=oid,
            object_repr=code,
            actor=request.user,
            request=request,
            action_code="SHIFT_TEMPLATE_DELETE",
        )
        messages.success(request, "Đã xóa ca làm việc.")
        return redirect("backoffice:shift_list")

    return render(request, "backoffice/org/shifts/confirm_delete.html", {"obj": obj})

@login_required
@permission_required("organization.change_shifttemplate", raise_exception=True)
def shift_restore(request, pk):
    obj = get_object_or_404(ShiftTemplate, pk=pk)

    if request.method == "POST":
        if not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])
            audit_log(
                action_verb="UPDATE",
                object_type="shift",
                object_id=obj.id,
                object_repr=obj.code,
                actor=request.user,
                changes={"is_active": {"old": False, "new": True}},
                request=request,
                action_code="SHIFT_TEMPLATE_RESTORE",
            )
            messages.success(request, "Đã khôi phục hoạt động ca làm việc.")
        else:
            messages.info(request, "Ca làm việc này đang hoạt động.")
        return redirect("backoffice:shift_list")

    return render(
        request,
        "backoffice/org/shifts/confirm_restore.html",
        {"obj": obj},
    )

