from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.backoffice.services.dashboard import (
    OverviewDailyService,
    OverviewPeriodService,
    parse_date,
)


@login_required
def dashboard(request):
    today = timezone.localdate()
    mode = (request.GET.get("mode") or "daily").strip().lower()
    if mode not in ("daily", "period"):
        mode = "daily"

    selected_unit_id = None
    raw_unit = (request.GET.get("unit") or "").strip()
    if raw_unit:
        try:
            selected_unit_id = int(raw_unit)
        except Exception:
            selected_unit_id = None

    if mode == "period":
        from_date = parse_date(request.GET.get("from_date")) or today.replace(day=1)
        to_date = parse_date(request.GET.get("to_date")) or today
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        # Tránh vô tình query quá rộng ở màn tổng quan; báo cáo sâu có thể xử lý riêng.
        if (to_date - from_date).days > 366:
            from_date = to_date - timedelta(days=366)
        group_by = (request.GET.get("group_by") or "day").strip().lower()
        context = OverviewPeriodService(
            request,
            from_date=from_date,
            to_date=to_date,
            selected_unit_id=selected_unit_id,
            group_by=group_by,
        ).build()
    else:
        work_date = parse_date(request.GET.get("date")) or parse_date(request.GET.get("work_date")) or today
        context = OverviewDailyService(
            request,
            work_date=work_date,
            selected_unit_id=selected_unit_id,
        ).build()

    return render(request, "backoffice/dashboard.html", context)
