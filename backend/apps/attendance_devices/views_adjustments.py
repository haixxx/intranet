from datetime import date

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from apps.hr.models import Employee
from .forms_adjustments import ManualAdjustmentSelectForm, ManualAdjustmentForm
from .models_adjustments import AttendanceManualAdjustment
from .services_overlay import overlay_day
from .models import AttendanceDayFacts


@login_required
@permission_required("attendance_devices.add_attendancemanualadjustment", raise_exception=True)
def day_adjust_select(request):
    """
    Chọn nhân sự + ngày để điều chỉnh.
    """
    if request.method == "POST":
        form = ManualAdjustmentSelectForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["employee_code"].strip()
            wd = form.cleaned_data["work_date"]
            return redirect("attendance_devices:day_adjust_form", employee_code=code, work_date=wd.isoformat())
    else:
        form = ManualAdjustmentSelectForm()
    return render(request, "backoffice/attendance_devices/day_adjust_select.html", {"form": form})


@login_required
@permission_required("attendance_devices.add_attendancemanualadjustment", raise_exception=True)
def day_adjust_form(request, employee_code: str, work_date: str):
    """
    Form điều chỉnh mốc ngày cho 1 nhân sự.
    """
    emp = get_object_or_404(Employee, employee_code=employee_code)
    try:
        y, m, d = [int(x) for x in work_date.split("-")]
        wd = date(y, m, d)
    except Exception:
        messages.error(request, "Ngày không hợp lệ.")
        return redirect("attendance_devices:day_adjust_select")

    facts = AttendanceDayFacts.objects.filter(employee=emp, work_date=wd).first()

    if request.method == "POST":
        form = ManualAdjustmentForm(request.POST)
        if form.is_valid():
            adj = AttendanceManualAdjustment.objects.create(
                employee=emp,
                work_date=wd,
                in1=form.cleaned_data.get("in1"),
                out1=form.cleaned_data.get("out1"),
                in2=form.cleaned_data.get("in2"),
                out2=form.cleaned_data.get("out2"),
                reason_code=form.cleaned_data.get("reason_code"),
                note=form.cleaned_data.get("note") or "",
                applied_by=request.user,
                is_active=True,
            )
            overlay_day(emp.id, wd)
            messages.success(request, "Đã áp điều chỉnh và cập nhật mốc hiệu lực.")
            return redirect("attendance_devices:day_adjust_form", employee_code=employee_code, work_date=work_date)
    else:
        form = ManualAdjustmentForm()

    return render(request, "backoffice/attendance_devices/day_adjust_form.html", {
        "form": form,
        "employee": emp,
        "work_date": wd,
        "facts": facts,
    })