from datetime import datetime as dt

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import permission_required

from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceBatch
from apps.attendance.services_bs import build_expected_roster, compute_roster_diff, apply_roster_diff


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

    batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()
    if not batch:
        return JsonResponse({"ok": False, "error": "Chưa có danh sách nháp"}, status=400)

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

    expected = build_expected_roster(batch.unit, batch.work_date)
    diff = compute_roster_diff(batch, expected)
    res = apply_roster_diff(batch, diff)
    return JsonResponse({"ok": True, "applied": res, "message": "Đã đồng bộ roster nháp theo điều động hiện tại."})