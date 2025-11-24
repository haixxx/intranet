from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from apps.audit.utils import audit_log

def login_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect('backoffice:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            audit_log(
                action_verb="LOGIN",
                object_type="auth",
                object_id=user.pk,
                object_repr=user.username,
                actor=user,
                request=request,
                action_code="AUTH_LOGIN",
            )
            return redirect('backoffice:dashboard')
        else:
            messages.error(request, "Sai thông tin đăng nhập")

    return render(request, 'core/login.html', {})

@login_required
def logout_view(request: HttpRequest):
    u = request.user
    logout(request)
    audit_log(
        action_verb="LOGOUT",
        object_type="auth",
        object_id=u.pk,
        object_repr=u.username,
        actor=u,
        request=request,
        action_code="AUTH_LOGOUT",
    )
    return redirect('core:login')