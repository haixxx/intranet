from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.db.models import Q
from apps.audit.models import AuditLog

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
def audit_list(request):
    q = request.GET.get('q', '').strip()
    qs = AuditLog.objects.select_related('actor').all()
    if q:
        qs = qs.filter(
            Q(action_verb__icontains=q) |
            Q(action_code__icontains=q) |
            Q(object_type__icontains=q) |
            Q(object_id__icontains=q) |
            Q(object_repr__icontains=q) |
            Q(actor__username__icontains=q)
        )
    qs = qs[:500]
    return render(request, 'backoffice/audit/list.html', {
        'logs': qs,
        'query': q,
    })