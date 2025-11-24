from .models import AuditLog

def _get_client_ip(request):
    if not request:
        return None
    # Nếu có proxy/nginx về sau, xử lý X-Forwarded-For tại đây
    return request.META.get('REMOTE_ADDR')

def audit_log(
    *,
    action_verb: str,
    object_type: str,
    object_id=None,
    object_repr="",
    actor=None,
    changes=None,
    extra=None,
    request=None,
    severity="INFO",
    action_code: str = "",
):
    AuditLog.objects.create(
        action_verb=action_verb,
        action_code=action_code or "",
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else "",
        object_repr=(object_repr or "")[:255],
        actor=actor,
        changes=changes or {},
        extra=extra or {},
        ip_address=_get_client_ip(request),
        severity=severity,
    )