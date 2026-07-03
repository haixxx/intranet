from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import render

from apps.audit.models import AuditLog

from .utils.pagination import paginate_queryset


@login_required
@permission_required("audit.view_auditlog", raise_exception=True)
def audit_list(request):
    q = request.GET.get("q", "").strip()
    qs = AuditLog.objects.select_related("actor").order_by("-created_at", "-id")
    if q:
        qs = qs.filter(
            Q(action_verb__icontains=q)
            | Q(action_code__icontains=q)
            | Q(object_type__icontains=q)
            | Q(object_id__icontains=q)
            | Q(object_repr__icontains=q)
            | Q(actor__username__icontains=q)
        )
    context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    context.update({"logs": context["items"], "query": q})
    return render(request, "backoffice/audit/list.html", context)
