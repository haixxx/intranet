from datetime import date

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q

from apps.organization.models import OrgUnit
from apps.hr.models import Employee
from .models import AttendanceDayFacts
from .models_adjustments import AttendanceManualAdjustment
from .services_overlay import overlay_day
from .constants import ReasonCode


@login_required
@permission_required("attendance_devices.add_attendancemanualadjustment", raise_exception=True)
def day_adjust_bulk(request):
    """
    Điều chỉnh mốc ngày theo kiểu danh sách (nhiều nhân sự).
    - GET: chọn ngày + đơn vị, lọc nhanh theo tổ/chuỗi (mã/tên), hiển thị computed/effective, sửa nhiều dòng.
    - POST: tạo AttendanceManualAdjustment cho các dòng có mốc nhập, áp overlay.
    """
    # Lấy danh sách đơn vị chấm công (chỉ Phòng/Ban/Phân xưởng)
    units_qs = OrgUnit.objects.filter(type__in=["DEPT", "WORKSHOP", "PLANT"]).order_by("name")

    work_date_str = (request.GET.get("date") or "").strip()
    unit_id_str = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()
    team_id = (request.GET.get("team") or "").strip()

    if request.method == "POST":
        # Nhận hidden các tham số để render lại sau khi áp dụng
        work_date_str = request.POST.get("date", work_date_str) or work_date_str
        unit_id_str = request.POST.get("unit", unit_id_str) or unit_id_str
        q = request.POST.get("q", q) or q
        team_id = request.POST.get("team", team_id) or team_id

        # Áp chỉnh
        try:
            y, m, d = [int(x) for x in work_date_str.split("-")]
            wd = date(y, m, d)
        except Exception:
            messages.error(request, "Ngày không hợp lệ.")
            return redirect("attendance_devices:day_adjust_bulk")

        if not unit_id_str:
            messages.error(request, "Vui lòng chọn đơn vị.")
            return redirect("attendance_devices:day_adjust_bulk")

        unit = get_object_or_404(OrgUnit, pk=int(unit_id_str))

        applied = 0
        affected_emp_ids = set()

        for key, val in request.POST.items():
            for slot in ("in1", "out1", "in2", "out2"):
                pref = f"{slot}_"
                if key.startswith(pref):
                    emp_id_part = key[len(pref):].strip()
                    if not emp_id_part.isdigit():
                        continue
                    emp_id = int(emp_id_part)

                    in1 = request.POST.get(f"in1_{emp_id}", "") or None
                    out1 = request.POST.get(f"out1_{emp_id}", "") or None
                    in2 = request.POST.get(f"in2_{emp_id}", "") or None
                    out2 = request.POST.get(f"out2_{emp_id}", "") or None
                    if not any([in1, out1, in2, out2]):
                        break

                    reason_row = request.POST.get(f"reason_{emp_id}", "") or ""
                    note_row = request.POST.get(f"note_{emp_id}", "") or ""

                    from datetime import time as dtime
                    def parse_t(s):
                        try:
                            if not s:
                                return None
                            hh, mm = [int(x) for x in s.split(":")]
                            return dtime(hh, mm)
                        except Exception:
                            return None

                    AttendanceManualAdjustment.objects.create(
                        employee_id=emp_id,
                        work_date=wd,
                        in1=parse_t(in1),
                        out1=parse_t(out1),
                        in2=parse_t(in2),
                        out2=parse_t(out2),
                        reason_code=reason_row or ReasonCode.OTHER,
                        note=note_row or "",
                        applied_by=request.user,
                        is_active=True,
                    )
                    overlay_day(emp_id, wd)
                    applied += 1
                    affected_emp_ids.add(emp_id)
                    break  # tránh tạo lặp dòng nhiều lần

        messages.success(request, f"Đã áp điều chỉnh {applied} dòng.")
        return redirect(f"{request.path}?date={work_date_str}&unit={unit_id_str}&q={q}&team={team_id}")

    # GET render danh sách
    items = []
    unit_obj = None
    teams = []
    if work_date_str and unit_id_str:
        try:
            y, m, d = [int(x) for x in work_date_str.split("-")]
            wd = date(y, m, d)
        except Exception:
            wd = None

        unit_obj = OrgUnit.objects.filter(pk=int(unit_id_str)).first()
        if unit_obj:
            # Lấy danh sách tổ trực thuộc đơn vị để lọc
            teams = OrgUnit.objects.filter(parent=unit_obj).order_by("name")

            # Lọc nhân sự theo unit và các team (đúng schema Employee: unit, team)
            emp_qs = Employee.objects.filter(
                Q(unit=unit_obj) |
                Q(team=unit_obj) |
                Q(team__parent=unit_obj)
            ).distinct()

            if q:
                emp_qs = emp_qs.filter(Q(employee_code__icontains=q) | Q(full_name__icontains=q))
            if team_id and team_id.isdigit():
                emp_qs = emp_qs.filter(team_id=int(team_id))

            emp_qs = emp_qs.order_by("full_name", "employee_code")[:800]  # giới hạn bảo vệ UI

            facts_map = {
                df.employee_id: df
                for df in AttendanceDayFacts.objects.filter(work_date=wd, employee_id__in=emp_qs.values_list("id", flat=True))
            }

            for emp in emp_qs:
                df = facts_map.get(emp.id)
                items.append({
                    "emp": emp,
                    "facts": df,
                    # computed
                    "in1": getattr(df, "in1", None),
                    "out1": getattr(df, "out1", None),
                    "in2": getattr(df, "in2", None),
                    "out2": getattr(df, "out2", None),
                    # effective + nguồn
                    "eff_in1": getattr(df, "effective_in1", None),
                    "eff_out1": getattr(df, "effective_out1", None),
                    "eff_in2": getattr(df, "effective_in2", None),
                    "eff_out2": getattr(df, "effective_out2", None),
                    "src_in1": getattr(df, "source_in1", ""),
                    "src_out1": getattr(df, "source_out1", ""),
                    "src_in2": getattr(df, "source_in2", ""),
                    "src_out2": getattr(df, "source_out2", ""),
                })

    return render(request, "backoffice/attendance_devices/day_adjust_bulk.html", {
        "units_qs": units_qs,
        "work_date": work_date_str,
        "unit_id": unit_id_str,
        "q": q,
        "teams": teams,
        "team_id": team_id,
        "items": items,
    })