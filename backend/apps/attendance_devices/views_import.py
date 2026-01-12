from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms_adjustments import DayFactsImportForm
from .services_import import parse_upload, apply_import


@login_required
@permission_required("attendance_devices.add_attendanceimportbatch", raise_exception=True)
def dayfacts_import(request):
    """
    Upload CSV/XLSX các mốc ngày: employee_code, work_date, in1, out1, in2, out2, note
    Chọn mode: FILL_MISSING_ONLY (mặc định) hoặc OVERWRITE_EXPLICIT
    """
    preview_rows = []
    errors = []

    if request.method == "POST":
        form = DayFactsImportForm(request.POST, request.FILES)
        if form.is_valid():
            f = request.FILES["file"]
            rows, errors = parse_upload(f)
            if errors:
                for e in errors:
                    messages.error(request, e)
                return render(request, "backoffice/attendance_devices/import_dayfacts.html", {
                    "form": form,
                    "preview_rows": preview_rows,
                    "errors": errors,
                })
            preview_rows = rows

            if request.POST.get("apply") == "1":
                batch = apply_import(
                    rows=rows,
                    user=request.user,
                    mode=form.cleaned_data["mode"],
                    reason_code=form.cleaned_data.get("reason_code") or "",
                    note=form.cleaned_data.get("note") or "",
                )
                messages.success(request, f"Đã áp import: áp dụng {batch.summary_json.get('applied', 0)}, lỗi {batch.summary_json.get('errors', 0)}.")
                return redirect("attendance_devices:dayfacts_import")

            return render(request, "backoffice/attendance_devices/import_dayfacts.html", {
                "form": form,
                "preview_rows": preview_rows,
                "errors": [],
            })
    else:
        form = DayFactsImportForm()

    return render(request, "backoffice/attendance_devices/import_dayfacts.html", {
        "form": form,
        "preview_rows": preview_rows,
        "errors": errors,
    })