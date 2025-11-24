from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import Q
from apps.core.forms import UserCreateForm, UserUpdateForm, AssignRolesForm
from apps.audit.utils import audit_log
from .utils.permissions import permission_or_message

User = get_user_model()

@permission_or_message('auth.view_user')
def user_list(request):
    q = request.GET.get('q', '').strip()
    qs = User.objects.all().order_by('username')
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(full_name__icontains=q) | Q(email__icontains=q))
    return render(request, 'backoffice/users/list.html', {'users': qs, 'query': q})

@permission_or_message('auth.add_user')
def user_create(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            new_user = form.save()
            audit_log(
                action_verb="CREATE",
                object_type="user",
                object_id=new_user.pk,
                object_repr=new_user.username,
                actor=request.user,
                changes={"fields": {f: getattr(new_user, f, None) for f in ["username","email","full_name"]}},
                request=request,
                action_code="USER_CREATE",
            )
            messages.success(request, "Đã tạo người dùng.")
            return redirect('backoffice:user_list')
    else:
        form = UserCreateForm()
    return render(request, 'backoffice/users/create.html', {'form': form})

@permission_or_message('auth.change_user')
def user_edit(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        old_values = {f: getattr(target, f, None) for f in ["full_name","email","is_active"]}
        form = UserUpdateForm(request.POST, instance=target)
        if form.is_valid():
            updated = form.save()
            new_values = {f: getattr(updated, f, None) for f in old_values.keys()}
            diff = {}
            for k in old_values:
                if old_values[k] != new_values[k]:
                    diff[k] = {"old": old_values[k], "new": new_values[k]}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="user",
                    object_id=updated.pk,
                    object_repr=updated.username,
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="USER_UPDATE",
                )
            messages.success(request, "Đã cập nhật người dùng.")
            return redirect('backoffice:user_list')
    else:
        form = UserUpdateForm(instance=target)
    return render(request, 'backoffice/users/edit.html', {'form': form, 'target': target})

@permission_or_message('auth.change_user')
def user_roles(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        before = set(target.groups.values_list("id", flat=True))
        form = AssignRolesForm(request.POST, user_instance=target)
        if form.is_valid():
            form.save(target)
            after = set(target.groups.values_list("id", flat=True))
            added = list(after - before)
            removed = list(before - after)
            if added or removed:
                audit_log(
                    action_verb="UPDATE",
                    object_type="user",
                    object_id=target.pk,
                    object_repr=target.username,
                    actor=request.user,
                    extra={"added_group_ids": added, "removed_group_ids": removed},
                    request=request,
                    action_code="USER_ROLES_UPDATE",
                )
            messages.success(request, "Đã cập nhật vai trò người dùng.")
            return redirect('backoffice:user_edit', user_id=target.id)
    else:
        form = AssignRolesForm(user_instance=target)
    return render(request, 'backoffice/users/roles.html', {'form': form, 'target': target})

@permission_or_message('auth.change_user')
def user_deactivate(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        if target.is_active:
            old = target.is_active
            target.is_active = False
            target.save(update_fields=['is_active'])
            audit_log(
                action_verb="UPDATE",
                object_type="user",
                object_id=target.pk,
                object_repr=target.username,
                actor=request.user,
                changes={"is_active": {"old": old, "new": False}},
                request=request,
                action_code="USER_DEACTIVATE",
            )
            messages.success(request, "Đã vô hiệu hóa tài khoản.")
        return redirect('backoffice:user_list')
    return render(request, 'backoffice/users/confirm_deactivate.html', {'target': target})

@permission_or_message('auth.change_user')
def user_activate(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        if not target.is_active:
            old = target.is_active
            target.is_active = True
            target.save(update_fields=['is_active'])
            audit_log(
                action_verb="UPDATE",
                object_type="user",
                object_id=target.pk,
                object_repr=target.username,
                actor=request.user,
                changes={"is_active": {"old": old, "new": True}},
                request=request,
                action_code="USER_ACTIVATE",
            )
            messages.success(request, "Đã kích hoạt tài khoản.")
        return redirect('backoffice:user_list')
    return render(request, 'backoffice/users/confirm_activate.html', {'target': target})