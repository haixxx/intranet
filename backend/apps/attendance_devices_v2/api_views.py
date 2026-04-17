from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse, HttpRequest
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AttendanceDeviceAPIKeyV2,
    AttendanceDeviceAgentV2,
    AttendanceDeviceV2,
    AttendanceIngestLogV2,
    AttendanceRawPunchV2,
)


# =========================
# Helpers: Auth
# =========================

def _json_error(message: str, status: int = 400, **extra: Any) -> JsonResponse:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _get_bearer_token(request: HttpRequest) -> str | None:
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if not auth:
        return None
    # Expect: "Bearer <token>"
    parts = auth.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _auth_agent(request: HttpRequest) -> AttendanceDeviceAgentV2 | JsonResponse:
    """
    Xác thực agent bằng Bearer API key.
    """
    token = _get_bearer_token(request)
    if not token:
        return _json_error(str(_("Thiếu Authorization Bearer token.")), status=401)

    key_obj = AttendanceDeviceAPIKeyV2.objects.select_related("agent").filter(key=token).first()
    if not key_obj:
        return _json_error(str(_("API key không hợp lệ.")), status=401)

    if not key_obj.is_valid_now():
        return _json_error(str(_("API key không còn hiệu lực hoặc agent chưa được kích hoạt.")), status=401)

    return key_obj.agent


def _require_same_agent(agent_from_key: AttendanceDeviceAgentV2, agent_id: int) -> JsonResponse | None:
    """
    Chặn việc dùng key của agent A để gọi API của agent B.
    """
    if agent_from_key.id != agent_id:
        return _json_error(str(_("Agent không khớp với API key.")), status=403)
    return None


def _parse_dt(value: str) -> datetime:
    """
    Parse datetime ISO-8601.
    Hỗ trợ cả 'Z' (UTC).
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# =========================
# API: Heartbeat
# =========================

@csrf_exempt
@require_POST
def agent_heartbeat(request: HttpRequest, agent_id: int) -> JsonResponse:
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    err = _require_same_agent(agent, agent_id)
    if err:
        return err

    # Cho phép body rỗng, nhưng nếu có thì parse
    try:
        body = request.body.decode("utf-8") if request.body else "{}"
        payload = json.loads(body or "{}")
    except Exception:
        payload = {}

    # Update last seen + info cơ bản
    AttendanceDeviceAgentV2.objects.filter(id=agent.id).update(
        last_seen_at=dj_timezone.now(),
        hostname=payload.get("hostname", agent.hostname) or agent.hostname,
        ip_address=payload.get("ip", agent.ip_address) or agent.ip_address,
        version=payload.get("version", agent.version) or agent.version,
    )

    return JsonResponse({"ok": True})


# =========================
# API: Get devices assigned
# =========================

@require_GET
def agent_devices(request: HttpRequest, agent_id: int) -> JsonResponse:
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    err = _require_same_agent(agent, agent_id)
    if err:
        return err

    devices = AttendanceDeviceV2.objects.filter(assigned_agent_id=agent.id, is_active=True).order_by("name")

    return JsonResponse({
        "ok": True,
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "host": d.host,
                "port": d.port,
                "timezone": d.timezone,
                "connect_mode": d.connect_mode,
                "is_active": d.is_active,
                "last_cursor_json": d.last_cursor_json,
            }
            for d in devices
        ],
    })


# =========================
# API: Ingest raw punches
# =========================

@csrf_exempt
@require_POST
def raw_punches_batch(request: HttpRequest) -> JsonResponse:
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    # Parse JSON
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return _json_error(str(_("Body JSON không hợp lệ.")), status=400)

    device_id = payload.get("device_id")
    if not device_id:
        return _json_error(str(_("Thiếu device_id.")), status=400)

    # device_id trong JSON có thể là string -> cast
    try:
        device_id_int = int(device_id)
    except Exception:
        return _json_error(str(_("device_id không hợp lệ.")), status=400)

    device = AttendanceDeviceV2.objects.filter(id=device_id_int).first()
    if not device:
        return _json_error(str(_("Không tìm thấy thiết bị.")), status=404)

    # Check device assigned to this agent
    if device.assigned_agent_id != agent.id:
        return _json_error(str(_("Thiết bị không thuộc agent này.")), status=403)

    events = payload.get("events") or []
    if not isinstance(events, list):
        return _json_error(str(_("events phải là danh sách.")), status=400)

    max_batch = getattr(settings, "ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE", 2000)
    if len(events) > max_batch:
        return _json_error(str(_("Batch quá lớn.")), status=413, max_batch=max_batch)

    batch_id = (payload.get("batch_id") or "").strip()
    cursor = payload.get("cursor")

    started_at = dj_timezone.now()
    log = AttendanceIngestLogV2.objects.create(
        device=device,
        agent=agent,
        started_at=started_at,
        success=False,
    )

    processed = 0
    duplicates = 0
    rejected = 0

    # Insert raw punches
    try:
        with transaction.atomic():
            for e in events:
                try:
                    device_user_id = str(e.get("device_user_id") or "").strip()
                    if not device_user_id:
                        rejected += 1
                        continue

                    event_time_local_s = str(e.get("event_time_local") or "").strip()
                    event_time_utc_s = str(e.get("event_time_utc") or "").strip()
                    if not event_time_local_s or not event_time_utc_s:
                        rejected += 1
                        continue

                    event_time_local = _parse_dt(event_time_local_s)
                    event_time_utc = _parse_dt(event_time_utc_s)

                    method = str(e.get("method") or "OTHER").strip().upper()
                    device_event_id = e.get("device_event_id")
                    if device_event_id is not None:
                        device_event_id = str(device_event_id).strip() or None

                    meta = e.get("meta")

                    # dedup_hash: nếu agent không gửi thì tự tính
                    dedup_hash = str(e.get("dedup_hash") or "").strip()
                    if not dedup_hash:
                        dedup_hash = AttendanceRawPunchV2.compute_dedup_hash(
                            device_id=device.id,
                            device_user_id=device_user_id,
                            event_time_local_iso=event_time_local_s,
                            method=method,
                        )

                    try:
                        AttendanceRawPunchV2.objects.create(
                            device=device,
                            agent=agent,
                            batch_id=batch_id,
                            device_user_id=device_user_id,
                            event_time_local=event_time_local,
                            event_time_utc=event_time_utc,
                            method=method,
                            device_event_id=device_event_id,
                            dedup_hash=dedup_hash,
                            meta_json=meta if isinstance(meta, (dict, list)) else None,
                            ingested_at=dj_timezone.now(),
                        )
                        processed += 1
                    except IntegrityError:
                        # Trùng (idempotency)
                        duplicates += 1
                        continue

                except Exception:
                    rejected += 1
                    continue

            # Update cursor + last_pull_at cho device
            if cursor is not None:
                device.last_cursor_json = cursor
            device.last_pull_at = dj_timezone.now()
            device.save(update_fields=["last_cursor_json", "last_pull_at"])

            log.processed = processed
            log.duplicates = duplicates
            log.rejected = rejected
            log.success = True
            log.accepted_cursor_snapshot = cursor if cursor is not None else None
            log.finished_at = dj_timezone.now()
            log.save(update_fields=[
                "processed", "duplicates", "rejected", "success",
                "accepted_cursor_snapshot", "finished_at"
            ])

    except Exception as ex:
        log.processed = processed
        log.duplicates = duplicates
        log.rejected = rejected
        log.success = False
        log.error_message = str(ex)
        log.finished_at = dj_timezone.now()
        log.save(update_fields=["processed", "duplicates", "rejected", "success", "error_message", "finished_at"])
        return _json_error(str(_("Lỗi ingest.")), status=500)

    return JsonResponse({
        "ok": True,
        "processed": processed,
        "duplicates": duplicates,
        "rejected": rejected,
        "accepted_cursor": cursor,
        "ingest_log_id": log.id,
    })