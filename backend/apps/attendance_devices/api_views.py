import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List

from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpRequest
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .models import AttendanceDevice, AttendanceRawEvent, AttendanceEventIngestLog
from .api_views_agents import _auth_agent

logger = logging.getLogger(__name__)


def _parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        raise ValueError("empty datetime")
    dt_str = dt_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(dt_str)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return dt


def _compute_dedup_hash(device_id: int, device_user_id: str, event_time_local: str, method: str) -> str:
    base = f"{device_id}::{device_user_id}::{event_time_local}::{method}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _log_ingest_failure(
    device: AttendanceDevice | None,
    started_at,
    error_message: str,
    last_cursor_snapshot=None,
):
    """
    Best-effort: log ingest failures for troubleshooting/ops.
    """
    try:
        AttendanceEventIngestLog.objects.create(
            device=device,
            started_at=started_at,
            finished_at=timezone.now(),
            count=0,
            duplicates=0,
            rejected=0,
            success=False,
            error_message=error_message,
            last_cursor_snapshot=last_cursor_snapshot,
        )
    except Exception:
        logger.exception("Failed to write AttendanceEventIngestLog failure entry.")


@csrf_exempt
@require_http_methods(["POST"])
def ingest_raw_events_batch(request: HttpRequest):
    """
    Ingest attendance events batch from agents.
    Auth: Bearer <api_key> (DeviceAPIKey)
    Notes:
      - Only allow ingest if device is assigned to this agent
      - Server commits cursor by saving AttendanceDevice.last_cursor_json
    """
    started_at = timezone.now()

    # Authenticate with Bearer token (agent api_key)
    agent = _auth_agent(request)
    if not agent:
        logger.warning("Bearer auth failed for ingest_raw_events_batch")
        _log_ingest_failure(device=None, started_at=started_at, error_message="Unauthorized: missing/invalid Bearer token")
        return JsonResponse({"ok": False, "error": "Unauthorized: missing/invalid Bearer token"}, status=401)

    # Parse JSON payload
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Invalid JSON: {e}")
        _log_ingest_failure(device=None, started_at=started_at, error_message=f"invalid_json: {e}")
        return JsonResponse({"ok": False, "error": f"invalid_json: {e}"}, status=400)

    device_ref = (payload.get("device_id") or "").strip()
    batch_id = (payload.get("batch_id") or "").strip()
    cursor = payload.get("cursor") or {}
    events: List[Dict[str, Any]] = payload.get("events") or []

    max_batch = int(getattr(settings, "ATTENDANCE_INGEST_MAX_BATCH_SIZE", 1000))

    # Validate request
    if not device_ref or not events:
        _log_ingest_failure(device=None, started_at=started_at, error_message="missing device_id or events", last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": "missing device_id or events"}, status=400)

    if len(events) > max_batch:
        _log_ingest_failure(device=None, started_at=started_at, error_message=f"batch_too_large: {len(events)}>{max_batch}", last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": f"batch_too_large: {len(events)}>{max_batch}"}, status=413)

    # Find device (prefer pk)
    device = None
    if device_ref.isdigit():
        device = AttendanceDevice.objects.filter(pk=int(device_ref)).first()

    if not device:
        logger.warning(f"Device not found: {device_ref} (batch_id={batch_id})")
        _log_ingest_failure(device=None, started_at=started_at, error_message=f"device_not_found: {device_ref}", last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": "device_not_found"}, status=404)

    if not device.is_active:
        logger.warning(f"Device inactive: {device.id} (batch_id={batch_id})")
        _log_ingest_failure(device=device, started_at=started_at, error_message="device_inactive", last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": "device_inactive"}, status=403)

    # Enforce assigned agent
    if getattr(device, "assigned_agent_id", None) != agent.id:
        msg = f"Forbidden: device {device.id} is not assigned to agent {agent.id}"
        logger.warning(msg)
        _log_ingest_failure(device=device, started_at=started_at, error_message=msg, last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": msg}, status=403)

    processed = 0
    duplicates = 0
    rejected = 0

    try:
        with transaction.atomic():
            for ev in events:
                try:
                    device_user_id = (ev.get("device_user_id") or "").strip()
                    event_time_local_str = (ev.get("event_time_local") or "").strip()
                    event_time_utc_str = (ev.get("event_time_utc") or "").strip()
                    method = (ev.get("method") or "OTHER").strip()
                    direction = (ev.get("direction") or "UNKNOWN").strip()
                    device_event_id = ev.get("device_event_id")
                    meta = ev.get("meta") or {}

                    if not device_user_id or not event_time_local_str or not event_time_utc_str:
                        rejected += 1
                        continue

                    event_time_local = _parse_iso(event_time_local_str)
                    event_time_utc = _parse_iso(event_time_utc_str)

                    dedup_hash = _compute_dedup_hash(device.id, device_user_id, event_time_local_str, method)

                    # Check for duplicates (prefer device_event_id)
                    if device_event_id:
                        if AttendanceRawEvent.objects.filter(device=device, device_event_id=device_event_id).exists():
                            duplicates += 1
                            continue

                    if AttendanceRawEvent.objects.filter(device=device, dedup_hash=dedup_hash).exists():
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

                except Exception as e:
                    logger.error(f"Event processing error: {e}", exc_info=True)
                    rejected += 1

            # Commit cursor on device (server is source of truth)
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

    except Exception as e:
        logger.exception("Ingest transaction failed")
        _log_ingest_failure(device=device, started_at=started_at, error_message=f"ingest_failed: {e}", last_cursor_snapshot=cursor)
        return JsonResponse({"ok": False, "error": f"ingest_failed: {e}"}, status=500)

    logger.info(
        f"Ingest completed for device {device.id} (agent={agent.id}, batch_id={batch_id}): "
        f"processed={processed}, duplicates={duplicates}, rejected={rejected}"
    )

    return JsonResponse(
        {
            "ok": True,
            "processed": processed,
            "duplicates": duplicates,
            "rejected": rejected,
            "accepted_cursor": device.last_cursor_json,
        },
        status=200,
    )