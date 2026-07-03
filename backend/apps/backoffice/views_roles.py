from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.utils import audit_log
from apps.core.forms import RoleUpdateForm

from .utils.pagination import paginate_queryset


@login_required
@permission_required("auth.view_group", raise_exception=True)
def role_list(request):
    q = request.GET.get("q", "").strip()
    roles = Group.objects.annotate(permission_count=Count("permissions", distinct=True)).order_by("name", "id")
    if q:
        roles = roles.filter(name__icontains=q)
    context = paginate_queryset(request, roles, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    context.update({"roles": context["items"], "query": q})
    return render(request, "backoffice/roles/list.html", context)


@login_required
@permission_required("auth.add_group", raise_exception=True)
def role_create(request):
    if request.method == "POST":
        form = RoleUpdateForm(request.POST)
        if form.is_valid():
            role = form.save()
            audit_log(
                action_verb="CREATE",
                object_type="group",
                object_id=role.pk,
                object_repr=role.name,
                actor=request.user,
                changes={"fields": {"name": role.name, "permission_ids": list(role.permissions.values_list("id", flat=True))}},
                request=request,
                action_code="ROLE_CREATE",
            )
            messages.success(request, "Đã tạo vai trò.")
            return redirect("backoffice:role_list")
    else:
        form = RoleUpdateForm()
    return render(request, "backoffice/roles/edit.html", {"form": form, "create": True})


@login_required
@permission_required("auth.change_group", raise_exception=True)
def role_edit(request, role_id):
    role = get_object_or_404(Group, pk=role_id)
    if request.method == "POST":
        old_perms = set(role.permissions.values_list("id", flat=True))
        form = RoleUpdateForm(request.POST, instance=role)
        if form.is_valid():
            form.save()
            new_perms = set(role.permissions.values_list("id", flat=True))
            added = list(new_perms - old_perms)
            removed = list(old_perms - new_perms)
            if added or removed:
                audit_log(
                    action_verb="UPDATE",
                    object_type="group",
                    object_id=role.pk,
                    object_repr=role.name,
                    actor=request.user,
                    extra={"added_permission_ids": added, "removed_permission_ids": removed},
                    request=request,
                    action_code="ROLE_PERMISSIONS_UPDATE",
                )
            messages.success(request, "Cập nhật role thành công.")
            return redirect("backoffice:role_list")
    else:
        form = RoleUpdateForm(instance=role)
    return render(request, "backoffice/roles/edit.html", {"form": form, "role": role})


@login_required
@permission_required("auth.delete_group", raise_exception=True)
def role_delete(request, role_id):
    role = get_object_or_404(Group, pk=role_id)
    if request.method == "POST":
        role_name = role.name
        role_id_str = str(role.pk)
        role.delete()
        audit_log(
            action_verb="DELETE",
            object_type="group",
            object_id=role_id_str,
            object_repr=role_name,
            actor=request.user,
            request=request,
            action_code="ROLE_DELETE",
        )
        messages.success(request, "Đã xóa role.")
        return redirect("backoffice:role_list")
    return render(request, "backoffice/roles/confirm_delete.html", {"role": role})
