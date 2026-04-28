from __future__ import annotations

from datetime import datetime, date as date_cls

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Sum, Count, Q

from apps.organization.models import OrgUnit

from .models_daily_audit import AttendanceDailyDeviceAuditV2


def _parse_date(s: str) -> date_cls | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@login_required
def report_units_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem báo cáo (v2)"
        }, status=403)

    from_date = _parse_date(request.GET.get("from"))
    to_date = _parse_date(request.GET.get("to"))
    threshold = request.GET.get("threshold") or "5"

    try:
        threshold_min = int(threshold)
    except Exception:
        threshold_min = 5
    if threshold_min not in (5, 10, 15):
        threshold_min = 5

    rows = []
    if from_date and to_date and from_date <= to_date:
        qs = AttendanceDailyDeviceAuditV2.objects.filter(
            work_date__gte=from_date,
            work_date__lte=to_date,
            is_exempt=False,
            expected_marks__gt=0,
        )

        late_q = Q(expected_in1=True, delta_in1_minutes__gt=threshold_min) | Q(expected_in2=True, delta_in2_minutes__gt=threshold_min)
        early_q = Q(expected_out1=True, delta_out1_minutes__lt=-threshold_min) | Q(expected_out2=True, delta_out2_minutes__lt=-threshold_min)

        agg = (
            qs.values("unit_id")
            .annotate(
                headcount=Count("id"),
                ok_people=Count("id", filter=Q(missing_marks=0)),
                missing_people=Count("id", filter=Q(missing_marks__gt=0)),
                missing_marks=Sum("missing_marks"),
                late_people=Count("id", filter=late_q),
                early_people=Count("id", filter=early_q),
            )
            .order_by("-missing_marks", "-missing_people")
        )

        unit_ids = [x["unit_id"] for x in agg]
        unit_map = {u.id: u for u in OrgUnit.objects.filter(id__in=unit_ids)}

        for x in agg:
            u = unit_map.get(x["unit_id"])
            headcount = x["headcount"] or 0
            ok_people = x["ok_people"] or 0
            rows.append({
                "unit_id": x["unit_id"],
                "unit_symbol": u.symbol if u else f"#{x['unit_id']}",
                "unit_name": u.name if u else "",
                "headcount": headcount,
                "ok_people": ok_people,
                "ok_rate": (ok_people / headcount * 100.0) if headcount else 0.0,
                "missing_people": x["missing_people"] or 0,
                "missing_marks": x["missing_marks"] or 0,
                "late_people": x["late_people"] or 0,
                "early_people": x["early_people"] or 0,
            })

    return render(request, "backoffice/attendance_devices_v2/report_units.html", {
        "from_date": request.GET.get("from") or "",
        "to_date": request.GET.get("to") or "",
        "threshold_min": threshold_min,
        "rows": rows,
    })