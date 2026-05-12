from __future__ import annotations

from datetime import datetime, date as date_cls, timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect
from django.utils import timezone as dj_timezone

from apps.hr.models import Employee
from apps.organization.models import OrgUnit

from .models_manual_punch import AttendanceManualPunch


def _parse_date(s: str) -> date_cls | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@login_required
def them_du_lieu_view(request):
    # Chỉ HR_ADMIN (hoặc ai được cấp quyền add) mới dùng UI này
    if not request.user.has_perm("attendance_devices_v2.add_attendancemanualpunch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.add_attendancemanualpunch",
            "title": "Bạn chưa được cấp quyền thêm dữ liệu chấm công"
        }, status=403)

    # Bộ lọc danh sách
    work_date = _parse_date(request.GET.get("date")) or dj_timezone.localdate()
    unit_raw = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()

    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")

    # POST: thêm mới
    if request.method == "POST":
        emp_id = (request.POST.get("employee_id") or "").strip()
        thoi_gian_raw = (request.POST.get("thoi_gian_local") or "").strip()  # datetime-local: YYYY-MM-DDTHH:MM
        ghi_chu = (request.POST.get("ghi_chu") or "").strip()

        if not emp_id.isdigit():
            messages.error(request, "Bạn cần chọn nhân sự.")
            return redirect(request.path)

        emp = Employee.objects.filter(id=int(emp_id)).first()
        if not emp:
            messages.error(request, "Không tìm thấy nhân sự.")
            return redirect(request.path)

        if not thoi_gian_raw:
            messages.error(request, "Bạn cần nhập thời gian.")
            return redirect(request.path)

        try:
            local_dt = dj_timezone.make_aware(
                datetime.strptime(thoi_gian_raw, "%Y-%m-%dT%H:%M"),
                dj_timezone.get_current_timezone(),
            )
        except Exception:
            messages.error(request, "Thời gian không hợp lệ. Định dạng đúng: YYYY-MM-DDTHH:MM")
            return redirect(request.path)

        AttendanceManualPunch.objects.create(
            employee=emp,
            thoi_gian_local=local_dt,
            thoi_gian_utc=local_dt.astimezone(timezone.utc),
            ghi_chu=ghi_chu,
            tao_boi=request.user,
        )

        messages.success(request, f"Đã thêm dữ liệu chấm công cho {emp.employee_code} - {emp.full_name}.")
        return redirect(f"{request.path}?date={work_date.strftime('%Y-%m-%d')}&unit={unit_raw}&q={q}")

    # GET: danh sách
    qs = AttendanceManualPunch.objects.select_related("employee").filter(
        thoi_gian_local__date=work_date
    )

    # lọc theo unit (theo employee.unit)
    if unit_raw.isdigit():
        qs = qs.filter(employee__unit_id=int(unit_raw))

    if q:
        qs = qs.filter(
            Q(employee__employee_code__icontains=q) |
            Q(employee__full_name__icontains=q) |
            Q(employee__card_id__icontains=q)
        )

    qs = qs.order_by("-thoi_gian_local")[:2000]

    # danh sách nhân sự cho dropdown (giới hạn theo unit nếu chọn)
    emp_qs = Employee.objects.filter(status=Employee.Status.ACTIVE)
    if unit_raw.isdigit():
        emp_qs = emp_qs.filter(unit_id=int(unit_raw))
    emp_qs = emp_qs.order_by("employee_code")[:2000]

    return render(request, "backoffice/attendance_devices_v2/them_du_lieu.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "unit": unit_raw,
        "q": q,
        "units": units,
        "employees": emp_qs,
        "rows": qs,
    })