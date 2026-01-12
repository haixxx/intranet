from datetime import date

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.contrib import messages

from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceCommit
from .services_compare import compare_day_vs_committed, apply_filters_and_sort


@login_required
@permission_required("attendance.view_attendancecommit", raise_exception=True)
def compare_committed_day(request):
    """
    So sánh giờ máy (effective) với công đã chốt (AttendanceCommit/CommitItem) theo ngày/đơn vị.
    Bộ lọc: tổ, chuỗi tìm kiếm, ngưỡng phút, chỉ muộn/chỉ sớm/chỉ thiếu mốc.
    Sắp xếp: severity, muộn/sớm AM/PM, tên, tổ, mã chế độ.
    """
    work_date_str = (request.GET.get("date") or "").strip()
    unit_id_str = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()
    team_id = (request.GET.get("team") or "").strip()

    only_late = (request.GET.get("only_late") == "1")
    only_early = (request.GET.get("only_early") == "1")
    only_missing = (request.GET.get("only_missing") == "1")
    threshold_min = int(request.GET.get("threshold") or "0")
    sort_by = (request.GET.get("sort") or "severity_desc").strip()

    units_qs = OrgUnit.objects.filter(type__in=["DEPT", "WORKSHOP", "PLANT"]).order_by("name")
    teams = []
    items = []

    if work_date_str and unit_id_str:
        try:
            y, m, d = [int(x) for x in work_date_str.split("-")]
            wd = date(y, m, d)
        except Exception:
            wd = None
            messages.error(request, "Ngày không hợp lệ.")

        unit = OrgUnit.objects.filter(pk=int(unit_id_str)).first()
        if unit and wd:
            # Báo nếu chưa có công đã chốt cho ngày/đơn vị
            if not AttendanceCommit.objects.filter(unit=unit, work_date=wd).exists():
                messages.info(request, f"Chưa có công đã chốt cho đơn vị '{unit.name}' ngày {work_date_str}.")
                return render(request, "backoffice/attendance_devices/compare_committed_day.html", {
                    "units_qs": units_qs,
                    "work_date": work_date_str,
                    "unit_id": unit_id_str,
                    "q": q,
                    "teams": [],
                    "team_id": team_id,
                    "items": [],
                    "only_late": only_late,
                    "only_early": only_early,
                    "only_missing": only_missing,
                    "threshold_min": threshold_min,
                    "sort_by": sort_by,
                })

            teams = OrgUnit.objects.filter(parent=unit).order_by("name")
            rows = compare_day_vs_committed(wd, unit, team_id=int(team_id) if team_id.isdigit() else None, q=q)
            items = apply_filters_and_sort(rows, only_late=only_late, only_early=only_early,
                                           only_missing=only_missing, threshold_min=threshold_min, sort_by=sort_by)

    return render(request, "backoffice/attendance_devices/compare_committed_day.html", {
        "units_qs": units_qs,
        "work_date": work_date_str,
        "unit_id": unit_id_str,
        "q": q,
        "teams": teams,
        "team_id": team_id,
        "items": items,
        "only_late": only_late,
        "only_early": only_early,
        "only_missing": only_missing,
        "threshold_min": threshold_min,
        "sort_by": sort_by,
    })