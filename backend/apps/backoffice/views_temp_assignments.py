from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from apps.hr.models import Employee, TempAssignment
from apps.organization.models import OrgUnit
from apps.hr.services import allowed_org_ids_for_user
from apps.audit.utils import audit_log


def _can_manage_assignments(user):
    return user.has_perm('hr.change_employee')


@login_required
@permission_required('hr.view_employee', raise_exception=True)
def temp_assignment_list(request):
    """
    Liệt kê điều động tạm thời (tối đa 500 gần nhất).
    Filter:
      q: tìm theo employee_code / full_name
      to_unit: ID đơn vị nhận
      status: ACTIVE/CANCELLED/EXPIRED
      over60=1: chỉ điều động ACTIVE > 60 ngày
    Chỉ hiển thị những điều động mà người dùng có quyền xem:
      - Nhân sự thuộc đơn vị trong phạm vi
      - Hoặc điều động tới đơn vị trong phạm vi
    """
    q = request.GET.get('q', '').strip()
    to_unit = request.GET.get('to_unit', '').strip()
    status = request.GET.get('status', '').strip()
    over60 = request.GET.get('over60', '').strip()

    scope_units = set(allowed_org_ids_for_user(request.user))

    qs = TempAssignment.objects.select_related('employee', 'from_unit', 'to_unit').order_by('-start_date', '-id')
    qs = qs.filter(
        Q(employee__unit_id__in=scope_units) |
        Q(to_unit_id__in=scope_units)
    )

    if q:
        qs = qs.filter(
            Q(employee__full_name__icontains=q) |
            Q(employee__employee_code__icontains=q)
        )
    if to_unit and to_unit.isdigit():
        qs = qs.filter(to_unit_id=int(to_unit))
    if status in (TempAssignment.Status.ACTIVE, TempAssignment.Status.CANCELLED, TempAssignment.Status.EXPIRED):
        qs = qs.filter(status=status)

    assignments = list(qs[:500])
    if over60 == '1':
        assignments = [a for a in assignments if a.status == TempAssignment.Status.ACTIVE and a.duration_days() > 60]

    units = OrgUnit.objects.filter(id__in=scope_units, type__in=['DEPARTMENT', 'DIVISION', 'WORKSHOP']).order_by('symbol')

    return render(request, 'backoffice/hr/assignments/list.html', {
        'items': assignments,
        'query': q,
        'to_unit_selected': to_unit,
        'status_selected': status,
        'over60': over60,
        'units': units,
        'manage_allowed': _can_manage_assignments(request.user),
    })


@login_required
@permission_required('hr.change_employee', raise_exception=True)
def temp_assignment_create(request):
    """
    Tạo điều động tạm thời. from_unit & snapshot sẽ tự động set trong model.
    """
    scope_units = set(allowed_org_ids_for_user(request.user))
    units = OrgUnit.objects.filter(id__in=scope_units, type__in=['DEPARTMENT', 'DIVISION', 'WORKSHOP']).order_by('symbol')

    if request.method == 'POST':
        employee_id = request.POST.get('employee_id', '').strip()
        to_unit_id = request.POST.get('to_unit_id', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        reason_code = request.POST.get('reason_code', '').strip()
        note = request.POST.get('note', '').strip()
        apply_flag = request.POST.get('apply_flag', 'on') in ('on', 'true', '1')

        errors = []
        employee = None
        to_unit = None

        if not employee_id or not employee_id.isdigit():
            errors.append("Thiếu hoặc sai employee_id.")
        else:
            employee = Employee.objects.filter(pk=int(employee_id)).select_related('unit').first()
            if not employee:
                errors.append("Nhân sự không tồn tại.")
            elif employee.unit_id not in scope_units:
                errors.append("Nhân sự ngoài phạm vi đơn vị của bạn.")

        if not to_unit_id or not to_unit_id.isdigit():
            errors.append("Thiếu to_unit_id.")
        else:
            to_unit = OrgUnit.objects.filter(pk=int(to_unit_id)).first()
            if not to_unit:
                errors.append("Đơn vị nhận không tồn tại.")
            elif to_unit.id not in scope_units:
                errors.append("Đơn vị nhận ngoài phạm vi quyền của bạn.")

        from datetime import datetime as dt
        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = dt.strptime(start_date, "%Y-%m-%d").date()
            except Exception:
                errors.append("start_date sai định dạng.")
        else:
            errors.append("Thiếu start_date.")

        if end_date:
            try:
                parsed_end = dt.strptime(end_date, "%Y-%m-%d").date()
            except Exception:
                errors.append("end_date sai định dạng.")

        if not reason_code:
            errors.append("Chọn lý do điều động.")

        if errors:
            messages.error(request, "; ".join(errors))
            return redirect('backoffice:temp_assignment_create')

        obj = TempAssignment(
            employee=employee,
            from_unit_id=employee.unit_id,               # set explicit
            to_unit=to_unit,
            start_date=parsed_start,
            end_date=parsed_end,
            reason_code=reason_code,
            note=note,
            status=TempAssignment.Status.ACTIVE,
            apply_flag=apply_flag,
            snapshot_employee_unit_at_create_id=employee.unit_id,
            created_by=request.user
        )
        try:
            obj.full_clean()
            obj.save()
            audit_log(action_verb="CREATE",
                      object_type="temp_assignment",
                      object_id=obj.id,
                      object_repr=f"{employee.employee_code}->{to_unit.symbol}",
                      actor=request.user,
                      request=request,
                      action_code="TEMP_ASSIGNMENT_CREATE")
            messages.success(request, "Đã tạo điều động.")
            return redirect('backoffice:temp_assignment_list')
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            return redirect('backoffice:temp_assignment_create')

    employees = Employee.objects.filter(unit_id__in=scope_units, status=Employee.Status.ACTIVE).order_by('employee_code')
    return render(request, 'backoffice/hr/assignments/form.html', {
        'employees': employees,
        'units': units,
        'reasons': TempAssignment.Reason.choices,
    })


@login_required
@permission_required('hr.change_employee', raise_exception=True)
def temp_assignment_cancel(request, pk):
    obj = get_object_or_404(TempAssignment.objects.select_related('employee', 'to_unit', 'from_unit'), pk=pk)
    scope_units = set(allowed_org_ids_for_user(request.user))
    if obj.employee.unit_id not in scope_units and obj.to_unit_id not in scope_units:
        messages.error(request, "Bạn không có quyền huỷ điều động này.")
        return redirect('backoffice:temp_assignment_list')

    if request.method == 'POST':
        if obj.status == TempAssignment.Status.ACTIVE:
            old_status = obj.status
            obj.status = TempAssignment.Status.CANCELLED
            obj.cancelled_at = timezone.now()
            obj.cancelled_by = request.user
            obj.save(update_fields=['status', 'cancelled_at', 'cancelled_by'])

            audit_log(action_verb="UPDATE",
                      object_type="temp_assignment",
                      object_id=obj.id,
                      object_repr=str(obj.id),
                      actor=request.user,
                      request=request,
                      action_code="TEMP_ASSIGNMENT_CANCEL",
                      changes={'status': {'old': old_status, 'new': obj.status}})
            messages.success(request, "Đã huỷ điều động.")
        else:
            messages.warning(request, "Trạng thái hiện tại không phải ACTIVE.")
        return redirect('backoffice:temp_assignment_list')

    return render(request, 'backoffice/hr/assignments/confirm_cancel.html', {
        'obj': obj
    })