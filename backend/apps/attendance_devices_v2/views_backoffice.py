from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from .forms import (
    AgentAPIKeyCreateForm,
    AttendanceDeviceAgentV2Form,
    AttendanceDeviceV2Form,
)
from .models import AttendanceDeviceAgentV2, AttendanceDeviceAPIKeyV2, AttendanceDeviceV2
from .sync_policy import get_device_sync_policy


# =========================
# Agents (v2)
# =========================

@login_required
@permission_required("attendance_devices_v2.view_attendancedeviceagentv2", raise_exception=True)
def agent_list(request):
    q = (request.GET.get("q") or "").strip()

    qs = AttendanceDeviceAgentV2.objects.all().order_by("-created_at")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hostname__icontains=q) | Q(ip_address__icontains=q))

    return render(request, "backoffice/attendance_devices_v2/agents_list.html", {
        "items": qs,
        "q": q,
    })


@login_required
@permission_required("attendance_devices_v2.add_attendancedeviceagentv2", raise_exception=True)
def agent_create(request):
    if request.method == "POST":
        form = AttendanceDeviceAgentV2Form(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, _("Đã tạo agent."))
            return redirect("attendance_devices_v2:agent_edit", agent_id=obj.id)
    else:
        form = AttendanceDeviceAgentV2Form()

    return render(request, "backoffice/attendance_devices_v2/agents_form.html", {
        "form": form,
        "create": True,
    })


@login_required
@permission_required("attendance_devices_v2.change_attendancedeviceagentv2", raise_exception=True)
def agent_edit(request, agent_id: int):
    obj = get_object_or_404(AttendanceDeviceAgentV2, pk=agent_id)

    if request.method == "POST":
        form = AttendanceDeviceAgentV2Form(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("Đã cập nhật agent."))
            return redirect("attendance_devices_v2:agent_edit", agent_id=obj.id)
    else:
        form = AttendanceDeviceAgentV2Form(instance=obj)

    keys = AttendanceDeviceAPIKeyV2.objects.filter(agent=obj).order_by("-created_at")
    key_form = AgentAPIKeyCreateForm()

    return render(request, "backoffice/attendance_devices_v2/agents_form.html", {
        "form": form,
        "obj": obj,
        "create": False,
        "keys": keys,
        "key_form": key_form,
    })


@login_required
@permission_required("attendance_devices_v2.change_attendancedeviceagentv2", raise_exception=True)
def agent_create_key(request, agent_id: int):
    obj = get_object_or_404(AttendanceDeviceAgentV2, pk=agent_id)

    if request.method != "POST":
        return redirect("attendance_devices_v2:agent_edit", agent_id=obj.id)

    form = AgentAPIKeyCreateForm(request.POST)
    if form.is_valid():
        key_obj = form.create_key(agent=obj)
        messages.success(request, _("Đã tạo API key mới: %s") % key_obj.key)
    else:
        messages.error(request, _("Không tạo được API key. Vui lòng kiểm tra dữ liệu."))

    return redirect("attendance_devices_v2:agent_edit", agent_id=obj.id)


# =========================
# Devices (v2)
# =========================

@login_required
@permission_required("attendance_devices_v2.view_attendancedevicev2", raise_exception=True)
def device_list(request):
    q = (request.GET.get("q") or "").strip()
    agent_id = (request.GET.get("agent") or "").strip()
    active = (request.GET.get("active") or "").strip()

    qs = AttendanceDeviceV2.objects.select_related("assigned_agent", "org_unit").all().order_by("name")

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(host__icontains=q) | Q(model__icontains=q) | Q(serial_no__icontains=q))
    if agent_id.isdigit():
        qs = qs.filter(assigned_agent_id=int(agent_id))
    if active in {"0", "1"}:
        qs = qs.filter(is_active=(active == "1"))

    agents = AttendanceDeviceAgentV2.objects.all().order_by("name")

    items = list(qs)
    for item in items:
        policy = get_device_sync_policy(item)
        item.sync_policy_summary = {
            "realtime_enabled": bool(policy.get("realtime_enabled")),
            "backfill_enabled": bool(policy.get("backfill_enabled")),
            "backfill_windows": [
                {
                    "name": window.get("name"),
                    "time": window.get("time") or "-",
                    "days": window.get("days") or "-",
                    "run_mode": window.get("run_mode") or "ALWAYS",
                    "enabled": bool(window.get("enabled", True)),
                }
                for window in policy.get("backfill_windows", [])
            ],
            "time_sync_enabled": bool(policy.get("time_sync_enabled")),
        }

    return render(request, "backoffice/attendance_devices_v2/devices_list.html", {
        "items": items,
        "q": q,
        "agent": agent_id,
        "active": active,
        "agents": agents,
    })


@login_required
@permission_required("attendance_devices_v2.add_attendancedevicev2", raise_exception=True)
def device_create(request):
    if request.method == "POST":
        form = AttendanceDeviceV2Form(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, _("Đã tạo thiết bị và lưu cấu hình Agent V2 an toàn."))
            return redirect("attendance_devices_v2:device_edit", device_id=obj.id)
    else:
        form = AttendanceDeviceV2Form()

    return render(request, "backoffice/attendance_devices_v2/devices_form.html", {
        "form": form,
        "create": True,
        "sync_policy_defaults": form.default_sync_policy,
    })


@login_required
@permission_required("attendance_devices_v2.change_attendancedevicev2", raise_exception=True)
def device_edit(request, device_id: int):
    obj = get_object_or_404(AttendanceDeviceV2, pk=device_id)

    if request.method == "POST":
        form = AttendanceDeviceV2Form(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("Đã cập nhật thiết bị và cấu hình Agent V2."))
            return redirect("attendance_devices_v2:device_edit", device_id=obj.id)
    else:
        form = AttendanceDeviceV2Form(instance=obj)

    return render(request, "backoffice/attendance_devices_v2/devices_form.html", {
        "form": form,
        "obj": obj,
        "create": False,
        "sync_policy_defaults": form.default_sync_policy,
    })