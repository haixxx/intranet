from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from datetime import date
from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceBatch, AttendanceCommit
from .views_attendance_batch import _time_to_str

@login_required
def batch_diff_api(request):
    """
    Trả về diff JSON giữa Batch và Commit theo ngày/đơn vị hiện tại.
    Hiển thị employee_name để dùng trong modal diff.
    """
    work_date_str = request.GET.get("date", "")
    unit_id = request.GET.get("unit", "")
    if not work_date_str or not unit_id:
        return JsonResponse({"ok": False, "error": "Thiếu tham số"}, status=400)

    try:
        y, m, d = map(int, work_date_str.split("-"))
        work_date = date(y, m, d)
    except Exception:
        return JsonResponse({"ok": False, "error": "Ngày không hợp lệ"}, status=400)

    unit = OrgUnit.objects.filter(id=int(unit_id), is_attendance_unit=True, is_active=True).first()
    if not unit:
        return JsonResponse({"ok": False, "error": "Đơn vị không hợp lệ"}, status=400)

    batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()
    commit = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
    if not batch or not commit:
        return JsonResponse({"ok": True, "items": []})

    commit_items = {ci.employee_id: ci for ci in commit.items.select_related("code", "employee")}
    items = []
    for it in batch.items.select_related("employee", "code"):
        ci = commit_items.get(it.employee_id)
        if not ci:
            continue
        emp_name = it.employee.full_name
        emp_code = it.employee.employee_code
        # code
        old_code = ci.code.code if ci.code else None
        new_code = it.code.code if it.code else None
        if old_code != new_code:
            items.append({
                "employee_id": it.employee_id,
                "employee_code": emp_code,
                "employee_name": emp_name,
                "field": "code",
                "old": old_code,
                "new": new_code,
            })
        # times
        for fname, old_v, new_v in [("in1", ci.in1, it.in1), ("out1", ci.out1, it.out1), ("in2", ci.in2, it.in2), ("out2", ci.out2, it.out2)]:
            if _time_to_str(old_v) != _time_to_str(new_v):
                items.append({
                    "employee_id": it.employee_id,
                    "employee_code": emp_code,
                    "employee_name": emp_name,
                    "field": fname,
                    "old": _time_to_str(old_v),
                    "new": _time_to_str(new_v),
                })
        # notes
        if (ci.notes or "") != (it.notes or ""):
            items.append({
                "employee_id": it.employee_id,
                "employee_code": emp_code,
                "employee_name": emp_name,
                "field": "notes",
                "old": ci.notes or "",
                "new": it.notes or "",
            })
        # include flag
        if bool(ci.include_in_unit) != bool(it.include_in_unit):
            items.append({
                "employee_id": it.employee_id,
                "employee_code": emp_code,
                "employee_name": emp_name,
                "field": "include_in_unit",
                "old": bool(ci.include_in_unit),
                "new": bool(it.include_in_unit),
            })
    return JsonResponse({"ok": True, "items": items})