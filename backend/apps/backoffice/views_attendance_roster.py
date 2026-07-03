from datetime import datetime as dt

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.contrib.auth.decorators import permission_required

from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceBatch
from apps.attendance.services_bs import build_expected_roster, compute_roster_diff, apply_roster_diff, scan_impacts_for_temp_assignment
from apps.backoffice.services.access_scope import unit_in_attendance_scope
try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None


@login_required
def batch_roster_diff_api(request):
    """
    API: trả diff roster giữa expected (theo BS hiện tại) và batch nháp.
    GET params: date (YYYY-MM-DD), unit (id)
    """
    work_date_str = request.GET.get("date", "")
    unit_id = request.GET.get("unit", "")
    if not work_date_str or not unit_id:
        return JsonResponse({"ok": False, "error": "Thiếu tham số"}, status=400)

    try:
        work_date = dt.strptime(work_date_str, "%Y-%m-%d").date()
    except Exception:
        return JsonResponse({"ok": False, "error": "Ngày không hợp lệ"}, status=400)

    unit = OrgUnit.objects.filter(id=int(unit_id), is_attendance_unit=True, is_active=True).first()
    if not unit:
        return JsonResponse({"ok": False, "error": "Đơn vị không hợp lệ"}, status=400)
    if not unit_in_attendance_scope(request.user, unit.id):
        return JsonResponse({"ok": False, "error": "Bạn không có quyền xem đơn vị này"}, status=403)

    batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()
    if not batch:
        return JsonResponse({"ok": False, "error": "Chưa có danh sách chấm công nháp"}, status=400)

    expected = build_expected_roster(unit, work_date)
    diff = compute_roster_diff(batch, expected)
    return JsonResponse({"ok": True, "diff": diff})


@login_required
@permission_required("attendance.change_attendancebatch", raise_exception=True)
def batch_roster_apply(request):
    """
    POST: áp dụng diff roster vào batch nháp hiện tại.
    Body: batch_id (form-encoded)
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Phương thức không hợp lệ"}, status=405)

    batch_id = request.POST.get("batch_id", "")
    if not batch_id or not batch_id.isdigit():
        return JsonResponse({"ok": False, "error": "Thiếu batch_id"}, status=400)

    batch = get_object_or_404(AttendanceBatch, pk=int(batch_id))
    if not unit_in_attendance_scope(request.user, batch.unit_id):
        return JsonResponse({"ok": False, "error": "Bạn không có quyền thao tác với đơn vị này"}, status=403)

    expected = build_expected_roster(batch.unit, batch.work_date)
    diff = compute_roster_diff(batch, expected)
    res = apply_roster_diff(batch, diff)

    if TempAssignment is not None:
        try:
            affected_qs = TempAssignment.objects.filter(
                apply_flag=True,
                status__in=TempAssignment.effective_statuses(),
                start_date__lte=batch.work_date,
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=batch.work_date)
            ).filter(
                Q(from_unit=batch.unit) | Q(to_unit=batch.unit)
            )
            for ta in affected_qs.select_related("employee", "from_unit", "to_unit"):
                scan_impacts_for_temp_assignment(ta)
        except Exception:
            pass

    return JsonResponse({"ok": True, "applied": res, "message": "Đã cập nhật danh sách chấm công nháp theo điều động hiện tại."})