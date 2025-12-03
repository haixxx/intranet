from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from apps.audit.utils import audit_log
from apps.attendance.models import AttendanceCode, AttendanceSettings
from apps.attendance.forms import AttendanceCodeForm, AttendanceSettingsForm


@login_required
def attendance_code_list(request):
    if not request.user.has_perm('attendance.view_attendancecode'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.view_attendancecode',
            'title': 'Bạn chưa được cấp quyền xem Mã chế độ'
        }, status=403)

    q = request.GET.get('q', '').strip()
    codes = AttendanceCode.objects.all().order_by('-priority', 'code')
    if q:
        codes = codes.filter(Q(code__icontains=q) | Q(label_vi__icontains=q))

    can_add = request.user.has_perm('attendance.add_attendancecode')
    can_change = request.user.has_perm('attendance.change_attendancecode')
    can_delete = request.user.has_perm('attendance.delete_attendancecode')

    return render(request, 'backoffice/attendance/code_list.html', {
        'items': codes,
        'query': q,
        'can_add': can_add,
        'can_change': can_change,
        'can_delete': can_delete,
    })


@login_required
def attendance_code_create(request):
    if not request.user.has_perm('attendance.add_attendancecode'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.add_attendancecode',
            'title': 'Bạn chưa được cấp quyền tạo Mã chế độ'
        }, status=403)

    if request.method == 'POST':
        form = AttendanceCodeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            audit_log(action_verb="CREATE", object_type="attendance_code", object_id=obj.id,
                      object_repr=obj.code, actor=request.user,
                      changes={'fields': {'code': obj.code, 'label_vi': obj.label_vi, 'priority': obj.priority}},
                      request=request, action_code="ATT_CODE_CREATE")
            messages.success(request, "Đã tạo mã chế độ.")
            return redirect('backoffice:attendance_code_list')
    else:
        form = AttendanceCodeForm()

    return render(request, 'backoffice/attendance/code_form.html', {
        'form': form,
        'create': True
    })


@login_required
def attendance_code_edit(request, pk):
    if not request.user.has_perm('attendance.change_attendancecode'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.change_attendancecode',
            'title': 'Bạn chưa được cấp quyền sửa Mã chế độ'
        }, status=403)

    obj = get_object_or_404(AttendanceCode, pk=pk)
    if request.method == 'POST':
        old = {
            'code': obj.code,
            'label_vi': obj.label_vi,
            'segments_am_type': obj.segments_am_type,
            'segments_pm_type': obj.segments_pm_type,
            'requires_am_work': obj.requires_am_work,
            'requires_pm_work': obj.requires_pm_work,
            'priority': obj.priority,
            'is_active': obj.is_active
        }
        form = AttendanceCodeForm(request.POST, instance=obj)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {'old': str(v), 'new': str(nv)}
            if diff:
                audit_log(action_verb="UPDATE", object_type="attendance_code", object_id=updated.id,
                          object_repr=updated.code, actor=request.user, changes=diff, request=request,
                          action_code="ATT_CODE_UPDATE")
            messages.success(request, "Đã cập nhật mã chế độ.")
            return redirect('backoffice:attendance_code_list')
    else:
        form = AttendanceCodeForm(instance=obj)

    return render(request, 'backoffice/attendance/code_form.html', {
        'form': form,
        'obj': obj,
        'create': False
    })


@login_required
def attendance_code_delete(request, pk):
    if not request.user.has_perm('attendance.delete_attendancecode'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.delete_attendancecode',
            'title': 'Bạn chưa được cấp quyền xoá Mã chế độ'
        }, status=403)

    obj = get_object_or_404(AttendanceCode, pk=pk)
    if request.method == 'POST':
        code = obj.code
        obj.delete()
        audit_log(action_verb="DELETE", object_type="attendance_code", object_id=pk,
                  object_repr=code, actor=request.user, request=request, action_code="ATT_CODE_DELETE")
        messages.success(request, "Đã xoá mã chế độ.")
        return redirect('backoffice:attendance_code_list')

    return render(request, 'backoffice/attendance/code_confirm_delete.html', {
        'obj': obj
    })


@login_required
def attendance_settings_view(request):
    if not request.user.has_perm('attendance.change_attendancesettings'):
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'attendance.change_attendancesettings',
            'title': 'Bạn chưa được cấp quyền cập nhật cấu hình chấm công'
        }, status=403)

    settings = AttendanceSettings.objects.first()
    if not settings:
        settings = AttendanceSettings.objects.create()

    if request.method == 'POST':
        form = AttendanceSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            obj = form.save()
            audit_log(action_verb="UPDATE", object_type="attendance_settings", object_id=obj.id,
                      object_repr="settings", actor=request.user,
                      changes={'fields': {
                          'window_minutes': obj.window_minutes,
                          'cluster_minutes': obj.cluster_minutes,
                          'round_registration_to_hour': obj.round_registration_to_hour
                      }},
                      request=request, action_code="ATT_SETTINGS_UPDATE")
            messages.success(request, "Đã cập nhật cấu hình đối chiếu.")
            return redirect('backoffice:attendance_settings')
    else:
        form = AttendanceSettingsForm(instance=settings)

    return render(request, 'backoffice/attendance/settings_form.html', {
        'form': form
    })