import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List

from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpRequest
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .models import AttendanceDevice, AttendanceRawEvent, AttendanceEventIngestLog
from .utils import parse_hmac_auth_header, verify_hmac_signature


def _parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        raise ValueError("empty datetime")
    dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


def _compute_dedup_hash(device_id: int, device_user_id: str, event_time_local: str, method: str) -> str:
    base = f"{device_id}::{device_user_id}::{event_time_local}::{method}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


@csrf_exempt
@require_http_methods(["POST"])
def ingest_raw_events_batch(request: HttpRequest):
    try:
        client_id, ts_str, sig_hex = parse_hmac_auth_header(request)
        verify_hmac_signature(request.body, client_id, ts_str, sig_hex)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"auth_failed: {e}"}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"invalid_json: {e}"}, status=400)

    device_ref = (payload.get("device_id") or "").strip()
    batch_id = (payload.get("batch_id") or "").strip()
    cursor = payload.get("cursor") or {}
    events: List[Dict[str, Any]] = payload.get("events") or []

    max_batch = int(getattr(settings, "ATTENDANCE_INGEST_MAX_BATCH_SIZE", 1000))
    if not device_ref or not events:
        return JsonResponse({"ok": False, "error": "missing device_id or events"}, status=400)
    if len(events) > max_batch:
        return JsonResponse({"ok": False, "error": f"batch_too_large: {len(events)}>{max_batch}"}, status=413)

    device = None
    if device_ref.isdigit():
        device = AttendanceDevice.objects.filter(pk=int(device_ref)).first()
    if not device and ":" in device_ref:
        host, port_str = device_ref.split(":", 1)
        try:
            device = AttendanceDevice.objects.filter(host=host.strip(), port=int(port_str)).first()
        except Exception:
            device = None
    if not device:
        return JsonResponse({"ok": False, "error": "device_not_found"}, status=404)
    if not device.is_active:
        return JsonResponse({"ok": False, "error": "device_inactive"}, status=403)

    started_at = timezone.now()
    processed = 0
    duplicates = 0
    rejected = 0

    with transaction.atomic():
        for ev in events:
            try:
                device_user_id = (ev.get("device_user_id") or "").strip()
                event_time_local_str = (ev.get("event_time_local") or "").strip()
                event_time_utc_str = (ev.get("event_time_utc") or "").strip()
                method = (ev.get("method") or "OTHER").strip()
                direction = (ev.get("direction") or "UNKNOWN").strip()
                device_event_id = (ev.get("device_event_id") or None)
                meta = ev.get("meta") or {}

                if not device_user_id or not event_time_local_str or not event_time_utc_str:
                    rejected += 1
                    continue

                event_time_local = _parse_iso(event_time_local_str)
                event_time_utc = _parse_iso(event_time_utc_str)

                dedup_hash = _compute_dedup_hash(device.id, device_user_id, event_time_local_str, method)

                obj = None
                if device_event_id:
                    obj = AttendanceRawEvent.objects.filter(device=device, device_event_id=device_event_id).first()
                if obj:
                    duplicates += 1
                    continue

                obj = AttendanceRawEvent.objects.filter(device=device, dedup_hash=dedup_hash).first()
                if obj:
                    duplicates += 1
                    continue

                AttendanceRawEvent.objects.create(
                    device=device,
                    device_user_id=device_user_id,
                    event_time_local=event_time_local,
                    event_time_utc=event_time_utc,
                    method=method if method in dict(AttendanceRawEvent.Method.choices) else AttendanceRawEvent.Method.OTHER,
                    direction=direction if direction in dict(AttendanceRawEvent.Direction.choices) else AttendanceRawEvent.Direction.UNKNOWN,
                    device_event_id=device_event_id,
                    dedup_hash=dedup_hash,
                    meta_json=meta,
                )
                processed += 1
            except Exception:
                rejected += 1

        device.last_cursor_json = cursor or {}
        device.last_pull_at = timezone.now()
        device.status = AttendanceDevice.Status.ONLINE
        device.save(update_fields=["last_cursor_json", "last_pull_at", "status"])

        AttendanceEventIngestLog.objects.create(
            device=device,
            started_at=started_at,
            finished_at=timezone.now(),
            count=processed,
            duplicates=duplicates,
            rejected=rejected,
            success=True,
            last_cursor_snapshot=device.last_cursor_json,
        )

    return JsonResponse({
        "ok": True,
        "processed": processed,
        "duplicates": duplicates,
        "rejected": rejected,
        "accepted_cursor": device.last_cursor_json,
    }, status=200)