from django.contrib.auth.decorators import login_required
from django.shortcuts import render
try:
    from apps.notifications.models import Notification
except Exception:
    Notification = None

@login_required
def notifications_list(request):
    notes = []
    if Notification:
        notes = list(Notification.objects.filter(user_id=request.user.id).order_by("-created_at")[:200])
    return render(request, "backoffice/notifications/list.html", {"notes": notes})