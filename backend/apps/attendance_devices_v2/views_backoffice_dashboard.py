from __future__ import annotations

from datetime import datetime, date as date_cls, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Sum, Count, Q

from apps.organization.models import OrgUnit

from .models import AttendanceDeviceV2
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
def report_dashboard_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem báo cáo (v2)"
        }, status=403)

    work_date = _parse_date(request.GET.get("date")) or date_cls.today()
    threshold = request.GET.get("threshold") or "5"
    try:
        threshold_min = int(threshold)
    except Exception:
        threshold_min = 5
    if threshold_min not in (5, 10, 15):
        threshold_min = 5

    qs = AttendanceDailyDeviceAuditV2.objects.filter(work_date=work_date, is_exempt=False, expected_marks__gt=0)

    # mẫu số
    headcount = qs.count()

    # đủ mốc
    ok_count = qs.filter(missing_marks=0).count()

    # thiếu mốc
    missing_people = qs.filter(missing_marks__gt=0).count()
    missing_marks = qs.aggregate(s=Sum("missing_marks"))["s"] or 0

    # đi muộn / về sớm theo mốc kỳ vọng:
    # late: delta_inX > threshold
    # early: delta_outX < -threshold
    late_q = Q()
    early_q = Q()
    # chỉ tính theo mốc expected (vì delta null nếu không matched, và missing đã riêng)
    late_q |= Q(expected_in1=True, delta_in1_minutes__gt=threshold_min)
    late_q |= Q(expected_in2=True, delta_in2_minutes__gt=threshold_min)
    early_q |= Q(expected_out1=True, delta_out1_minutes__lt=-threshold_min)
    early_q |= Q(expected_out2=True, delta_out2_minutes__lt=-threshold_min)

    late_people = qs.filter(late_q).count()
    early_people = qs.filter(early_q).count()

    # Top units by missing marks
    top_missing_units = (
        AttendanceDailyDeviceAuditV2.objects
        .filter(work_date=work_date, is_exempt=False, expected_marks__gt=0)
        .values("unit_id")
        .annotate(
            headcount=Count("id"),
            missing_people=Count("id", filter=Q(missing_marks__gt=0)),
            missing_marks=Sum("missing_marks"),
        )
        .order_by("-missing_marks")[:10]
    )
    unit_ids = [x["unit_id"] for x in top_missing_units]
    unit_map = {u.id: u for u in OrgUnit.objects.filter(id__in=unit_ids)}
    top_missing_units_rows = []
    for x in top_missing_units:
        u = unit_map.get(x["unit_id"])
        top_missing_units_rows.append({
            "unit_id": x["unit_id"],
            "unit_symbol": u.symbol if u else f"#{x['unit_id']}",
            "unit_name": u.name if u else "",
            "headcount": x["headcount"] or 0,
            "missing_people": x["missing_people"] or 0,
            "missing_marks": x["missing_marks"] or 0,
        })

    # Top units by late people
    top_late_units = (
        AttendanceDailyDeviceAuditV2.objects
        .filter(work_date=work_date, is_exempt=False, expected_marks__gt=0)
        .values("unit_id")
        .annotate(
            headcount=Count("id"),
            late_people=Count("id", filter=late_q),
        )
        .order_by("-late_people")[:10]
    )
    unit_ids2 = [x["unit_id"] for x in top_late_units]
    unit_map2 = {u.id: u for u in OrgUnit.objects.filter(id__in=unit_ids2)}
    top_late_units_rows = []
    for x in top_late_units:
        u = unit_map2.get(x["unit_id"])
        top_late_units_rows.append({
            "unit_id": x["unit_id"],
            "unit_symbol": u.symbol if u else f"#{x['unit_id']}",
            "unit_name": u.name if u else "",
            "headcount": x["headcount"] or 0,
            "late_people": x["late_people"] or 0,
        })

    # Device stats (v2)
    total_devices = AttendanceDeviceV2.objects.count()
    active_devices = AttendanceDeviceV2.objects.filter(is_active=True).count()
    assigned_devices = AttendanceDeviceV2.objects.filter(assigned_agent_id__isnull=False).count()

    now = datetime.now().astimezone()
    dt_24h = now - timedelta(hours=24)
    pulled_24h = AttendanceDeviceV2.objects.filter(last_pull_at__isnull=False, last_pull_at__gte=dt_24h).count()

    return render(request, "backoffice/attendance_devices_v2/report_dashboard.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "threshold_min": threshold_min,
        "headcount": headcount,
        "ok_count": ok_count,
        "missing_people": missing_people,
        "missing_marks": missing_marks,
        "late_people": late_people,
        "early_people": early_people,
        "top_missing_units": top_missing_units_rows,
        "top_late_units": top_late_units_rows,
        "total_devices": total_devices,
        "active_devices": active_devices,
        "assigned_devices": assigned_devices,
        "pulled_24h": pulled_24h,
    })