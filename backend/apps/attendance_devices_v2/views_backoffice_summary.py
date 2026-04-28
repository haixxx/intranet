from __future__ import annotations

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Count

from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceCommit

from .models import AttendancePunchMatchV2


@login_required
def audit_summary_view(request):
    """
    Summary: thống kê số mốc thiếu (MISSING) theo đơn vị/ngày.
    Query:
      - date=YYYY-MM-DD (required)
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem tổng hợp đối chiếu (v2)"
        }, status=403)

    work_date_str = (request.GET.get("date") or "").strip()
    work_date = None
    if work_date_str:
        try:
            work_date = datetime.strptime(work_date_str, "%Y-%m-%d").date()
        except Exception:
            work_date = None

    rows = []
    if work_date:
        qs = (
            AttendancePunchMatchV2.objects
            .filter(work_date=work_date, status=AttendancePunchMatchV2.Status.MISSING)
            .values("employee__unit_id")
            .annotate(missing_count=Count("id"))
            .order_by("-missing_count")
        )
        unit_ids = [x["employee__unit_id"] for x in qs]
        unit_map = {u.id: u for u in OrgUnit.objects.filter(id__in=unit_ids)}
        commit_units = set(AttendanceCommit.objects.filter(work_date=work_date).values_list("unit_id", flat=True))

        for x in qs:
            uid = x["employee__unit_id"]
            rows.append({
                "unit": unit_map.get(uid),
                "unit_id": uid,
                "missing_count": x["missing_count"],
                "has_commit": uid in commit_units,
            })

    return render(request, "backoffice/attendance_devices_v2/audit_summary.html", {
        "work_date": work_date_str,
        "rows": rows,
    })


@login_required
def audit_missing_export_csv(request):
    """
    Export CSV danh sách MISSING cho 1 đơn vị/ngày.
    Query:
      - date=YYYY-MM-DD
      - unit=<id>
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xuất dữ liệu đối chiếu (v2)"
        }, status=403)

    work_date_str = (request.GET.get("date") or "").strip()
    unit_raw = (request.GET.get("unit") or "").strip()
    try:
        work_date = datetime.strptime(work_date_str, "%Y-%m-%d").date()
    except Exception:
        return HttpResponse("Invalid date", status=400)
    if not unit_raw.isdigit():
        return HttpResponse("Invalid unit", status=400)
    unit_id = int(unit_raw)

    # Lấy run mới nhất cho unit/date (giống audit page)
    base_qs = AttendancePunchMatchV2.objects.select_related("employee").filter(
        work_date=work_date,
        employee__unit_id=unit_id,
        status=AttendancePunchMatchV2.Status.MISSING,
    )
    latest_run_id = base_qs.order_by("-created_at").values_list("compute_run_id", flat=True).first()
    if latest_run_id:
        base_qs = base_qs.filter(compute_run_id=latest_run_id)

    unit = OrgUnit.objects.filter(id=unit_id).first()
    unit_code = unit.symbol if unit and unit.symbol else str(unit_id)

    # CSV response
    filename = f"missing-punches-v2-{unit_code}-{work_date_str}.csv"
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'

    # UTF-8 BOM để Excel mở không lỗi tiếng Việt
    resp.write("\ufeff")

    # header
    resp.write("employee_code,full_name,target_field,target_time,status\n")

    for m in base_qs.order_by("employee__employee_code", "target_field"):
        emp = m.employee
        target_time = m.target_time_local.astimezone().strftime("%H:%M") if m.target_time_local else ""
        resp.write(f"{emp.employee_code},{emp.full_name},{m.target_field},{target_time},{m.status}\n")

    return resp