from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Max, Count  # ADD Count

from .models import AttendanceDevice, AttendanceEventIngestLog, AttendanceRawEvent  # ADD AttendanceRawEvent
from .forms import AttendanceDeviceForm
from apps.audit.utils import audit_log


@login_required
@permission_required("attendance_devices.view_attendancedevice", raise_exception=True)
def device_list(request):
    q = (request.GET.get("q") or "").strip()
    is_active = request.GET.get("active", "").strip()
    status = request.GET.get("status", "").strip()

    qs = AttendanceDevice.objects.all().order_by("name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(host__icontains=q) | Q(model__icontains=q) | Q(serial_no__icontains=q))
    if is_active in {"0", "1"}:
        qs = qs.filter(is_active=(is_active == "1"))
    if status:
        qs = qs.filter(status=status)

    # Lấy lỗi gần nhất từ logs (nếu có)
    last_logs = AttendanceEventIngestLog.objects.values("device_id").annotate(last_id=Max("id"))
    last_log_map = {row["device_id"]: row["last_id"] for row in last_logs}
    last_log_objs = AttendanceEventIngestLog.objects.filter(id__in=last_log_map.values())
    log_by_device = {x.device_id: x for x in last_log_objs}

    # Đếm số sự kiện chưa resolve theo device (employee is null)
    unresolved_counts = AttendanceRawEvent.objects.filter(employee__isnull=True).values("device_id").annotate(cnt=Count("id"))
    unresolved_by_device = {row["device_id"]: row["cnt"] for row in unresolved_counts}

    page = int(request.GET.get("page") or "1")
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(page)

    return render(request, "backoffice/attendance_devices/list.html", {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "q": q,
        "active": is_active,
        "status": status,
        "log_by_device": log_by_device,
        "unresolved_by_device": unresolved_by_device,  # NEW
    })


@login_required
@permission_required("attendance_devices.add_attendancedevice", raise_exception=True)
def device_create(request):
    if request.method == "POST":
        form = AttendanceDeviceForm(request.POST)
        if form.is_valid():
            obj = form.save()
            audit_log(
                action_verb="CREATE",
                object_type="attendance_device",
                object_id=obj.id,
                object_repr=f"{obj.name} ({obj.host}:{obj.port})",
                actor=request.user,
                changes={"fields": form.cleaned_data},
                request=request,
                action_code="ATT_DEV_CREATE",
            )
            messages.success(request, "Đã tạo thiết bị.")
            return redirect("attendance_devices:backoffice_device_list")
    else:
        form = AttendanceDeviceForm()
    return render(request, "backoffice/attendance_devices/form.html", {"form": form, "create": True})


@login_required
@permission_required("attendance_devices.change_attendancedevice", raise_exception=True)
def device_edit(request, device_id: int):
    obj = get_object_or_404(AttendanceDevice, pk=device_id)
    if request.method == "POST":
        old = {
            "name": obj.name, "host": obj.host, "port": obj.port,
            "brand": obj.brand, "model": obj.model, "serial_no": obj.serial_no,
            "timezone": obj.timezone, "is_active": obj.is_active,
            "connect_mode": obj.connect_mode, "notes": obj.notes,
        }
        form = AttendanceDeviceForm(request.POST, instance=obj)
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
                    object_type="attendance_device",
                    object_id=updated.id,
                    object_repr=f"{updated.name} ({updated.host}:{updated.port})",
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="ATT_DEV_UPDATE",
                )
            messages.success(request, "Đã cập nhật thiết bị.")
            return redirect("attendance_devices:backoffice_device_list")
    else:
        form = AttendanceDeviceForm(instance=obj)
    return render(request, "backoffice/attendance_devices/form.html", {"form": form, "obj": obj})


@login_required
@permission_required("attendance_devices.delete_attendancedevice", raise_exception=True)
def device_delete(request, device_id: int):
    obj = get_object_or_404(AttendanceDevice, pk=device_id)
    if request.method == "POST":
        oid = obj.id
        repr_ = f"{obj.name} ({obj.host}:{obj.port})"
        obj.delete()
        audit_log(
            action_verb="DELETE",
            object_type="attendance_device",
            object_id=oid,
            object_repr=repr_,
            actor=request.user,
            changes={},
            request=request,
            action_code="ATT_DEV_DELETE",
        )
        messages.success(request, "Đã xóa thiết bị.")
        return redirect("attendance_devices:backoffice_device_list")
    return render(request, "backoffice/attendance_devices/confirm_delete.html", {"obj": obj})


@login_required
@permission_required("attendance_devices.view_attendanceeventingestlog", raise_exception=True)
def device_logs(request, device_id: int):
    device = get_object_or_404(AttendanceDevice, pk=device_id)
    qs = AttendanceEventIngestLog.objects.filter(device=device).order_by("-started_at", "-id")
    page = int(request.GET.get("page") or "1")
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(page)
    return render(request, "backoffice/attendance_devices/logs.html", {
        "device": device,
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
    })