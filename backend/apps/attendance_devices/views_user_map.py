import csv
import io
from typing import List, Dict

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction

from .models import AttendanceDevice, AttendanceDeviceUserMap
from .forms import DeviceUserMapForm, DeviceUserMapBulkImportForm
from apps.hr.models import Employee
from apps.audit.utils import audit_log


@login_required
@permission_required("attendance_devices.view_attendancedeviceusermap", raise_exception=True)
def user_map_list(request, device_id: int):
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status", "").strip()

    maps = AttendanceDeviceUserMap.objects.filter(device=device).order_by("-is_active", "device_user_id")
    if q:
        maps = maps.filter(device_user_id__icontains=q) | maps.filter(employee__employee_code__icontains=q) | maps.filter(employee__full_name__icontains=q)
    if status in {"active", "inactive"}:
        maps = maps.filter(is_active=(status == "active"))

    return render(request, "backoffice/attendance_devices/user_map_list.html", {
        "device": device,
        "items": maps.select_related("employee"),
        "q": q, "status": status,
    })


@login_required
@permission_required("attendance_devices.add_attendancedeviceusermap", raise_exception=True)
def user_map_create(request, device_id: int):
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    if request.method == "POST":
        form = DeviceUserMapForm(request.POST, device=device)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.device = device
            obj.save()
            audit_log(
                action_verb="CREATE",
                object_type="attendance_device_user_map",
                object_id=obj.id,
                object_repr=f"{obj.device_id}:{obj.device_user_id}",
                actor=request.user,
                changes={"employee_id": getattr(obj.employee, "id", obj.employee), "notes": obj.notes},
                request=request,
                action_code="ATT_DEV_USER_MAP_CREATE",
            )
            messages.success(request, "Đã tạo mapping.")
            return redirect("attendance_devices:user_map_list", device_id=device.id)
    else:
        form = DeviceUserMapForm(device=device)
    return render(request, "backoffice/attendance_devices/user_map_form.html", {"form": form, "device": device, "create": True})


@login_required
@permission_required("attendance_devices.change_attendancedeviceusermap", raise_exception=True)
def user_map_edit(request, device_id: int, map_id: int):
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    obj = get_object_or_404(AttendanceDeviceUserMap, pk=map_id, device=device)
    if request.method == "POST":
        old = {
            "device_user_id": obj.device_user_id,
            "employee_id": getattr(obj.employee, "id", obj.employee),
            "is_active": obj.is_active,
            "notes": obj.notes,
        }
        form = DeviceUserMapForm(request.POST, instance=obj, device=device)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {"old": v, "new": nv}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="attendance_device_user_map",
                    object_id=updated.id,
                    object_repr=f"{updated.device_id}:{updated.device_user_id}",
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="ATT_DEV_USER_MAP_UPDATE",
                )
            messages.success(request, "Đã cập nhật mapping.")
            return redirect("attendance_devices:user_map_list", device_id=device.id)
    else:
        form = DeviceUserMapForm(instance=obj, device=device)
    return render(request, "backoffice/attendance_devices/user_map_form.html", {"form": form, "device": device, "obj": obj})


@login_required
@permission_required("attendance_devices.change_attendancedeviceusermap", raise_exception=True)
def user_map_deactivate(request, device_id: int, map_id: int):
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    obj = get_object_or_404(AttendanceDeviceUserMap, pk=map_id, device=device, is_active=True)
    if request.method == "POST":
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        audit_log(
            action_verb="UPDATE",
            object_type="attendance_device_user_map",
            object_id=obj.id,
            object_repr=f"{obj.device_id}:{obj.device_user_id}",
            actor=request.user,
            changes={"is_active": {"old": True, "new": False}},
            request=request,
            action_code="ATT_DEV_USER_MAP_DEACTIVATE",
        )
        messages.success(request, "Đã vô hiệu hóa mapping.")
        return redirect("attendance_devices:user_map_list", device_id=device.id)
    return render(request, "backoffice/attendance_devices/user_map_confirm_deactivate.html", {"device": device, "obj": obj})


@login_required
@permission_required("attendance_devices.add_attendancedeviceusermap", raise_exception=True)
def user_map_bulk_import(request, device_id: int):
    """
    Upload CSV: device_user_id,employee_code
    Xem trước, sau đó 'Áp dụng' để tạo/ cập nhật mapping.
    """
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    preview_rows: List[Dict] = []

    if request.method == "POST":
        form = DeviceUserMapBulkImportForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["csv_file"]
            deactivate_existing = bool(form.cleaned_data.get("deactivate_existing"))

            try:
                content = f.read().decode("utf-8")
            except Exception:
                messages.error(request, "Không đọc được tệp CSV. Vui lòng dùng mã hóa UTF-8.")
                return render(request, "backoffice/attendance_devices/user_map_bulk_import.html", {"form": form, "device": device})

            reader = csv.DictReader(io.StringIO(content))
            required_cols = {"device_user_id", "employee_code"}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                messages.error(request, "CSV phải có cột: device_user_id, employee_code.")
                return render(request, "backoffice/attendance_devices/user_map_bulk_import.html", {"form": form, "device": device})

            # Xem trước tối đa 50 dòng
            for idx, row in enumerate(reader):
                if idx >= 2000:
                    break  # bảo vệ kích thước lớn, vẫn cho import nhưng xem trước giới hạn
                uid = (row.get("device_user_id") or "").strip()
                code = (row.get("employee_code") or "").strip()
                emp = Employee.objects.filter(employee_code=code).first()
                preview_rows.append({
                    "device_user_id": uid,
                    "employee_code": code,
                    "employee_id": getattr(emp, "id", None),
                    "employee_name": getattr(emp, "full_name", None),
                    "valid": bool(uid and emp),
                })

            if request.POST.get("apply") == "1":
                # Áp dụng import
                created = 0
                updated = 0
                deactivated = 0
                errors = 0

                # Re-iterate full file to apply
                reader_apply = csv.DictReader(io.StringIO(content))
                with transaction.atomic():
                    for row in reader_apply:
                        uid = (row.get("device_user_id") or "").strip()
                        code = (row.get("employee_code") or "").strip()
                        emp = Employee.objects.filter(employee_code=code).first()
                        if not uid or not emp:
                            errors += 1
                            continue

                        existing_active = AttendanceDeviceUserMap.objects.filter(
                            device=device, device_user_id=uid, is_active=True
                        ).first()
                        if existing_active:
                            # update employee if changed
                            old_emp_id = getattr(existing_active.employee, "id", existing_active.employee)
                            if old_emp_id != emp.id:
                                existing_active.employee = emp
                                existing_active.save(update_fields=["employee"])
                                updated += 1
                            # deactivate_existing flag handled via separate deactivation if needed
                        else:
                            # Optionally deactivate all active mappings with same uid (safety)
                            if deactivate_existing:
                                deactivated += AttendanceDeviceUserMap.objects.filter(
                                    device=device, device_user_id=uid, is_active=True
                                ).update(is_active=False)
                            AttendanceDeviceUserMap.objects.create(
                                device=device, device_user_id=uid, employee=emp, is_active=True, notes=""
                            )
                            created += 1

                audit_log(
                    action_verb="IMPORT",
                    object_type="attendance_device_user_map_bulk",
                    object_id=device.id,
                    object_repr=f"{device.name} ({device.host}:{device.port})",
                    actor=request.user,
                    changes={"created": created, "updated": updated, "deactivated": deactivated, "errors": errors},
                    request=request,
                    action_code="ATT_DEV_USER_MAP_BULK_IMPORT",
                )
                messages.success(request, f"Áp dụng import: tạo {created}, cập nhật {updated}, vô hiệu hóa {deactivated}, lỗi {errors}.")
                return redirect("attendance_devices:user_map_list", device_id=device.id)

            # Render xem trước
            return render(request, "backoffice/attendance_devices/user_map_bulk_import.html", {
                "form": form, "device": device, "preview_rows": preview_rows
            })
    else:
        form = DeviceUserMapBulkImportForm()

    return render(request, "backoffice/attendance_devices/user_map_bulk_import.html", {"form": form, "device": device})