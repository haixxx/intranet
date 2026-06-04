from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.utils import audit_log
from apps.hr.models import Employee
from apps.organization.forms import JobTitleForm
from apps.organization.models import JobTitle


@login_required
@permission_required("organization.view_jobtitle", raise_exception=True)
def jobtitle_list(request):
    items = JobTitle.objects.order_by("is_active", "name")
    return render(request, "backoffice/org/jobtitles/list.html", {"items": items})


@login_required
@permission_required("organization.add_jobtitle", raise_exception=True)
def jobtitle_create(request):
    if request.method == "POST":
        form = JobTitleForm(request.POST)
        if form.is_valid():
            obj = form.save()
            audit_log(
                action_verb="CREATE",
                object_type="jobtitle",
                object_id=obj.id,
                object_repr=obj.name,
                actor=request.user,
                changes={"fields": {"name": obj.name, "code": obj.code}},
                request=request,
                action_code="JOBTITLE_CREATE",
            )
            messages.success(request, "Đã tạo chức danh.")
            return redirect("backoffice:jobtitle_list")
    else:
        form = JobTitleForm()
    return render(request, "backoffice/org/jobtitles/form.html", {"form": form, "create": True})


@login_required
@permission_required("organization.change_jobtitle", raise_exception=True)
def jobtitle_edit(request, pk):
    obj = get_object_or_404(JobTitle, pk=pk)
    if request.method == "POST":
        old = {"name": obj.name, "code": obj.code, "is_active": obj.is_active}
        form = JobTitleForm(request.POST, instance=obj)
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
                    object_type="jobtitle",
                    object_id=updated.id,
                    object_repr=updated.name,
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="JOBTITLE_UPDATE",
                )
            messages.success(request, "Đã cập nhật chức danh.")
            return redirect("backoffice:jobtitle_list")
    else:
        form = JobTitleForm(instance=obj)
    return render(request, "backoffice/org/jobtitles/form.html", {"form": form, "obj": obj})


@login_required
@permission_required("organization.delete_jobtitle", raise_exception=True)
def jobtitle_delete(request, pk):
    obj = get_object_or_404(JobTitle, pk=pk)

    used_by_employee = Employee.objects.filter(job_title=obj).exists()

    if request.method == "POST":
        if used_by_employee:
            if obj.is_active:
                obj.is_active = False
                obj.save(update_fields=["is_active"])
                audit_log(
                    action_verb="UPDATE",
                    object_type="jobtitle",
                    object_id=obj.id,
                    object_repr=obj.name,
                    actor=request.user,
                    changes={"is_active": {"old": True, "new": False}},
                    request=request,
                    action_code="JOBTITLE_DEACTIVATE_INSTEAD_OF_DELETE",
                )
                messages.warning(
                    request,
                    "Chức danh đang được gán cho nhân sự nên không xóa trực tiếp. Đã chuyển sang trạng thái ngừng hoạt động.",
                )
            else:
                messages.info(request, "Chức danh đang được sử dụng và đã ở trạng thái ngừng hoạt động.")
            return redirect("backoffice:jobtitle_list")

        oid, name = obj.id, obj.name
        obj.delete()
        audit_log(
            action_verb="DELETE",
            object_type="jobtitle",
            object_id=oid,
            object_repr=name,
            actor=request.user,
            request=request,
            action_code="JOBTITLE_DELETE",
        )
        messages.success(request, "Đã xóa chức danh.")
        return redirect("backoffice:jobtitle_list")

    return render(
        request,
        "backoffice/org/jobtitles/confirm_delete.html",
        {
            "obj": obj,
            "used_by_employee": used_by_employee,
        },
    )

@login_required
@permission_required("organization.change_jobtitle", raise_exception=True)
def jobtitle_restore(request, pk):
    obj = get_object_or_404(JobTitle, pk=pk)

    if request.method == "POST":
        if not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])
            audit_log(
                action_verb="UPDATE",
                object_type="jobtitle",
                object_id=obj.id,
                object_repr=obj.name,
                actor=request.user,
                changes={"is_active": {"old": False, "new": True}},
                request=request,
                action_code="JOBTITLE_RESTORE",
            )
            messages.success(request, "Đã khôi phục hoạt động chức danh.")
        else:
            messages.info(request, "Chức danh này đang hoạt động.")
        return redirect("backoffice:jobtitle_list")

    return render(
        request,
        "backoffice/org/jobtitles/confirm_restore.html",
        {"obj": obj},
    )

