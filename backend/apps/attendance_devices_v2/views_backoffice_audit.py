from __future__ import annotations

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Q

from apps.organization.models import OrgUnit
from apps.backoffice.services.access_scope import get_allowed_attendance_units, unit_in_attendance_scope
from apps.attendance.models import AttendanceSettings
from apps.attendance.models_batch import AttendanceCommit

from .models import AttendancePunchMatchV2


@login_required
def audit_matches_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem đối chiếu (v2)"
        }, status=403)

    work_date_str = (request.GET.get("date") or "").strip()
    unit_id_raw = (request.GET.get("unit") or "").strip()
    status = (request.GET.get("status") or "").strip().upper()
    q = (request.GET.get("q") or "").strip()

    units_qs = get_allowed_attendance_units(request.user)

    work_date = None
    if work_date_str:
        try:
            work_date = datetime.strptime(work_date_str, "%Y-%m-%d").date()
        except Exception:
            work_date = None

    unit_id_int = None
    if unit_id_raw.isdigit() and unit_in_attendance_scope(request.user, int(unit_id_raw)):
        unit_id_int = int(unit_id_raw)

    rows = []
    has_commit = False
    settings = AttendanceSettings.objects.first()

    if work_date and unit_id_int:
        has_commit = AttendanceCommit.objects.filter(unit_id=unit_id_int, work_date=work_date).exists()

        base_qs = AttendancePunchMatchV2.objects.select_related(
            "employee", "matched_punch", "matched_punch__best_device"
        ).filter(
            work_date=work_date,
            employee__unit_id=unit_id_int,
        )

        if status in ("MATCHED", "MISSING", "EXEMPT"):
            base_qs = base_qs.filter(status=status)

        if q:
            base_qs = base_qs.filter(
                Q(employee__employee_code__icontains=q) |
                Q(employee__full_name__icontains=q)
            )

        # Không cho user nhập run_id nữa: luôn lấy run gần nhất cho unit/date
        latest_run_id = base_qs.order_by("-created_at").values_list("compute_run_id", flat=True).first()
        if latest_run_id:
            base_qs = base_qs.filter(compute_run_id=latest_run_id)

        data = list(base_qs.order_by("employee__employee_code", "target_field"))

        emp_map = {}
        for m in data:
            emp = m.employee
            bucket = emp_map.get(emp.id)
            if not bucket:
                bucket = {"employee": emp, "IN1": None, "OUT1": None, "IN2": None, "OUT2": None}
                emp_map[emp.id] = bucket
            bucket[m.target_field] = m

        rows = list(emp_map.values())

    return render(request, "backoffice/attendance_devices_v2/audit_matches.html", {
        "units_qs": units_qs,
        "work_date": work_date_str,
        "unit_id_int": unit_id_int,   # dùng cái này để selected không bị nhảy
        "status": status,
        "q": q,
        "rows": rows,
        "has_commit": has_commit,
        "settings": settings,
    })