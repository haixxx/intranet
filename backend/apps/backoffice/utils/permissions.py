from functools import wraps
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

def permission_or_message(perm_codename: str):
    """
    Thay thế permission_required(... raise_exception=True)
    - Nếu user có quyền: chạy view
    - Nếu không: trả về trang thông báo thân thiện.
    """
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.has_perm(perm_codename):
                return view_func(request, *args, **kwargs)
            return render(request, 'backoffice/no_permission.html', {
                'perm_codename': perm_codename,
                'title': 'Bạn chưa được cấp quyền'
            }, status=200)
        return _wrapped
    return decorator