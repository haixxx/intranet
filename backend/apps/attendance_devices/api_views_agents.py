import json
from typing import Dict, Any
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.shortcuts import get_object_or_404

from .models import AttendanceDevice
from .models_agents import AttendanceDeviceAgent, DeviceAPIKey


def _auth_agent(request) -> AttendanceDeviceAgent | None:
    # Prefer request.headers (Django >= 2.2), fallback to META
    auth = request.headers.get("Authorization", "") or request.META.get("HTTP_AUTHORIZATION", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    else:
        token = ""
    if not token:
        return None

    key = DeviceAPIKey.objects.filter(key=token, is_active=True).select_related("agent").first()
    if not key:
        return None
    if key.expires_at and key.expires_at < timezone.now():
        return None
    return key.agent


@csrf_exempt
@require_http_methods(["POST"])
def agent_register(request):
    """
    Đăng ký agent: trả agent_id + api_key.
    Body JSON: {name, hostname, ip, version}
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    name = (payload.get("name") or "").strip() or "Windows Agent"
    hostname = (payload.get("hostname") or "").strip()
    ip = (payload.get("ip") or "").strip()
    version = (payload.get("version") or "").strip()

    agent = AttendanceDeviceAgent.objects.create(
        name=name, hostname=hostname, ip_address=ip, version=version, is_active=True
    )
    token = DeviceAPIKey.generate_key()
    DeviceAPIKey.objects.create(agent=agent, key=token, is_active=True)

    return JsonResponse({"ok": True, "agent_id": agent.id, "api_key": token})


@require_http_methods(["GET"])
def agent_devices(request, agent_id: int):
    """
    Danh sách thiết bị được phân công cho agent.
    Auth: Bearer token theo agent
    """
    agent = _auth_agent(request)
    if not agent or agent.id != int(agent_id):
        return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)

    devs = AttendanceDevice.objects.filter(assigned_agent=agent, is_active=True).order_by("name")
    data = []
    for d in devs:
        data.append({
            "id": d.id,
            "brand": d.brand,
            "connect_mode": d.connect_mode,
            "host": d.host,
            "port": d.port,
            "timezone": d.timezone,
            "is_active": d.is_active,
            "last_cursor_json": d.last_cursor_json,
            "sdk_profile": d.sdk_profile,
        })
    return JsonResponse({"ok": True, "devices": data})


@csrf_exempt
@require_http_methods(["POST"])
def agent_heartbeat(request, agent_id: int):
    """
    Nhịp sống của agent: tổng kết trạng thái, optional drift.
    Auth: Bearer token
    Body: {stats: {...}, drift_minutes: number?}
    """
    agent = _auth_agent(request)
    if not agent or agent.id != int(agent_id):
        return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    stats = payload.get("stats") or {}
    drift = payload.get("drift_minutes")

    agent.version = (payload.get("version") or agent.version)
    agent.updated_at = timezone.now()
    agent.save(update_fields=["version", "updated_at"])

    return JsonResponse({"ok": True, "received": {"stats": stats, "drift_minutes": drift}})


@csrf_exempt
@require_http_methods(["POST"])
def device_cursor_update(request, device_id: int):
    """
    Cập nhật tiến độ đọc cho thiết bị.
    Auth: Bearer token
    Body: {last_cursor_json: {...}}
    (Note: agent plan: KHÔNG dùng endpoint này nữa, cursor commit qua ingest)
    """
    agent = _auth_agent(request)
    if not agent:
        return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)

    dev = get_object_or_404(AttendanceDevice, pk=device_id)
    if dev.assigned_agent_id != agent.id:
        return JsonResponse({"ok": False, "error": "Forbidden: device not assigned to this agent"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    cursor = payload.get("last_cursor_json")

    dev.last_cursor_json = cursor
    dev.updated_at = timezone.now()
    dev.save(update_fields=["last_cursor_json", "updated_at"])

    return JsonResponse({"ok": True})