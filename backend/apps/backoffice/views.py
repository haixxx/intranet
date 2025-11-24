from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def dashboard(request):
    context = {
        "page_title": "Dashboard",
        "cards": [
            {"title": "Chấm công hôm nay", "value": "—"},
            {"title": "Suất ăn đăng ký", "value": "—"},
            {"title": "Cuộc họp trong ngày", "value": "—"},
        ],
    }
    return render(request, "backoffice/dashboard.html", context)