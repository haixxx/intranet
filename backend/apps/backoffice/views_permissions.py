from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group, Permission
from django.shortcuts import render

@login_required
@permission_required('auth.view_permission', raise_exception=True)
def permission_matrix(request):
    groups = list(Group.objects.all().order_by('name'))
    perms = Permission.objects.select_related('content_type').order_by('content_type__app_label', 'codename')

    perms_by_app = {}
    for p in perms:
        perms_by_app.setdefault(p.content_type.app_label, []).append(p)

    role_perm_ids = {g.id: set(g.permissions.values_list('id', flat=True)) for g in groups}

    return render(request, 'backoffice/roles/matrix.html', {
        'groups': groups,
        'perms_by_app': perms_by_app,
        'role_perm_ids': role_perm_ids,
    })