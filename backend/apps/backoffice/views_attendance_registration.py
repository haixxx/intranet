from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from apps.audit.utils import audit_log
from apps.attendance.forms_registration import AttendanceRegistrationForm
from apps.attendance.models_registration import AttendanceRegistration
from apps.organization.models import OrgUnit
from apps.hr.services import allowed_org_ids_for_user


@login_required
def attendance_reg_list(request):
    if not request.user.has_perm('attendance.view_attendanceregistration'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.view_attendanceregistration',
            'title': 'Bạn chưa được cấp quyền xem Đăng ký công'
        }, status=403)

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    date_from = request.GET.get('from', '').strip()
    date_to = request.GET.get('to', '').strip()

    scope_units = set(allowed_org_ids_for_user(request.user))
    regs = AttendanceRegistration.objects.select_related("employee", "code").filter(
        employee__unit_id__in=scope_units
    )

    if q:
        regs = regs.filter(Q(employee__full_name__icontains=q) | Q(employee__employee_code__icontains=q))
    if status in dict(AttendanceRegistration.Status.choices):
        regs = regs.filter(status=status)
    from datetime import date
    try:
        if date_from:
            y, m, d = map(int, date_from.split("-"))
            regs = regs.filter(work_date__gte=date(y, m, d))
        if date_to:
            y, m, d = map(int, date_to.split("-"))
            regs = regs.filter(work_date__lte=date(y, m, d))
    except Exception:
        pass

    regs = regs.order_by("-work_date", "employee__employee_code")

    return render(request, "backoffice/attendance/reg_list.html", {
        "items": regs[:1000],  # limit
        "query": q,
        "status_sel": status,
        "from": date_from,
        "to": date_to,
    })


@login_required
def attendance_reg_create(request):
    if not request.user.has_perm('attendance.add_attendanceregistration'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.add_attendanceregistration',
            'title': 'Bạn chưa được cấp quyền tạo Đăng ký công'
        }, status=403)

    if request.method == "POST":
        form = AttendanceRegistrationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.round_times_if_needed()
            obj.unit_accounting_id = obj.employee.unit_id  # mặc định đơn vị gốc, đối chiếu sẽ cập nhật
            obj.save()
            audit_log(action_verb="CREATE", object_type="attendance_registration", object_id=obj.id,
                      object_repr=f"{obj.employee.employee_code}-{obj.work_date}", actor=request.user,
                      changes={"fields": {"code": obj.code.code}}, request=request, action_code="ATT_REG_CREATE")
            messages.success(request, "Đã tạo đăng ký.")
            return redirect("backoffice:attendance_reg_list")
    else:
        form = AttendanceRegistrationForm()

    return render(request, "backoffice/attendance/reg_form.html", {
        "form": form,
        "create": True
    })


@login_required
def attendance_reg_edit(request, pk):
    if not request.user.has_perm('attendance.change_attendanceregistration'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.change_attendanceregistration',
            'title': 'Bạn chưa được cấp quyền sửa Đăng ký công'
        }, status=403)

    obj = get_object_or_404(AttendanceRegistration.objects.select_related("employee", "code"), pk=pk)
    if request.method == "POST":
        old_status = obj.status
        form = AttendanceRegistrationForm(request.POST, instance=obj)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.round_times_if_needed()
            updated.save()
            audit_log(action_verb="UPDATE", object_type="attendance_registration", object_id=updated.id,
                      object_repr=f"{updated.employee.employee_code}-{updated.work_date}", actor=request.user,
                      changes={"fields": {"status": {"old": old_status, "new": updated.status}}}, request=request,
                      action_code="ATT_REG_UPDATE")
            messages.success(request, "Đã cập nhật đăng ký.")
            return redirect("backoffice:attendance_reg_list")
    else:
        form = AttendanceRegistrationForm(instance=obj)

    return render(request, "backoffice/attendance/reg_form.html", {
        "form": form,
        "obj": obj
    })


@login_required
def attendance_reg_delete(request, pk):
    if not request.user.has_perm('attendance.delete_attendanceregistration'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.delete_attendanceregistration',
            'title': 'Bạn chưa được cấp quyền xóa Đăng ký công'
        }, status=403)

    obj = get_object_or_404(AttendanceRegistration, pk=pk)
    if request.method == "POST":
        key = f"{obj.employee.employee_code}-{obj.work_date}"
        obj.delete()
        audit_log(action_verb="DELETE", object_type="attendance_registration", object_id=pk,
                  object_repr=key, actor=request.user, request=request, action_code="ATT_REG_DELETE")
        messages.success(request, "Đã xóa đăng ký.")
        return redirect("backoffice:attendance_reg_list")

    return render(request, "backoffice/attendance/reg_confirm_delete.html", {
        "obj": obj
    })