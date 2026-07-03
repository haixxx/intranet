from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import render

from .utils.pagination import paginate_queryset


@login_required
@permission_required("auth.view_permission", raise_exception=True)
def permission_matrix(request):
    app_label = request.GET.get("app", "").strip()
    q = request.GET.get("q", "").strip()

    groups = list(Group.objects.prefetch_related("permissions").all().order_by("name", "id"))
    perms = Permission.objects.select_related("content_type").order_by("content_type__app_label", "content_type__model", "codename", "id")

    if app_label:
        perms = perms.filter(content_type__app_label=app_label)
    if q:
        perms = perms.filter(Q(codename__icontains=q) | Q(name__icontains=q))

    apps = list(
        ContentType.objects.filter(permission__isnull=False)
        .values_list("app_label", flat=True)
        .distinct()
        .order_by("app_label")
    )

    context = paginate_queryset(request, perms, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    page_perms = list(context["items"])

    perms_by_app = {}
    for permission in page_perms:
        perms_by_app.setdefault(permission.content_type.app_label, []).append(permission)

    role_perm_ids = {group.id: set(group.permissions.values_list("id", flat=True)) for group in groups}

    context.update(
        {
            "groups": groups,
            "perms_by_app": perms_by_app,
            "role_perm_ids": role_perm_ids,
            "apps": apps,
            "app_selected": app_label,
            "query": q,
        }
    )
    return render(request, "backoffice/roles/matrix.html", context)
