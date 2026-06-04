from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    context = {
        "page_title": "Tổng quan",
        "cards": [
            {
                "title": "Chấm công hôm nay",
                "value": "—",
                "description": "Sẽ tổng hợp sau khi chuẩn hóa xong module chấm công.",
            },
            {
                "title": "Thiết bị chấm công",
                "value": "V2",
                "description": "Module thiết bị chấm công v2 đang là module vận hành chính.",
            },
            {
                "title": "Trạng thái hệ thống",
                "value": "OK",
                "description": "Nền hệ thống đã qua check, migrate và collectstatic.",
            },
        ],
    }
    return render(request, "backoffice/dashboard.html", context)
