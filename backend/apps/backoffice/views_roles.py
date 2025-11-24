from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.contrib import messages
from apps.core.forms import RoleUpdateForm
from apps.audit.utils import audit_log

@login_required
@permission_required('auth.view_group', raise_exception=True)
def role_list(request):
    roles = Group.objects.all().order_by('name')
    return render(request, 'backoffice/roles/list.html', {'roles': roles})

@login_required
@permission_required('auth.change_group', raise_exception=True)
def role_edit(request, role_id):
    role = get_object_or_404(Group, pk=role_id)
    if request.method == 'POST':
        old_perms = set(role.permissions.values_list('id', flat=True))
        form = RoleUpdateForm(request.POST, instance=role)
        if form.is_valid():
            form.save()
            new_perms = set(role.permissions.values_list('id', flat=True))
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
            return redirect('backoffice:role_list')
    else:
        form = RoleUpdateForm(instance=role)
    return render(request, 'backoffice/roles/edit.html', {'form': form, 'role': role})

@login_required
@permission_required('auth.delete_group', raise_exception=True)
def role_delete(request, role_id):
    role = get_object_or_404(Group, pk=role_id)
    if request.method == 'POST':
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
        return redirect('backoffice:role_list')
    return render(request, 'backoffice/roles/confirm_delete.html', {'role': role})