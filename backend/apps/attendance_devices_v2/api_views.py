from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
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
    parts = auth.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _auth_agent(request: HttpRequest) -> AttendanceDeviceAgentV2 | JsonResponse:
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
    if agent_from_key.id != agent_id:
        return _json_error(str(_("Agent không khớp với API key.")), status=403)
    return None


def _parse_dt(value: Any) -> datetime:
    """
    Parse datetime ISO-8601 từ Agent.

    Hỗ trợ:
    - hậu tố Z;
    - offset +07:00 / +00:00;
    - chuỗi .NET có 7 chữ số phần giây, ví dụ .0000000+00:00.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value or "").strip()
        if not s:
            raise ValueError("datetime rỗng")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"

        # Python chỉ nhận tối đa 6 chữ số microsecond.
        s = re.sub(r"(\.\d{6})\d+(?=Z|[+-]\d{2}:?\d{2}$|$)", r"\1", s)
        dt = datetime.fromisoformat(s)

    if dj_timezone.is_naive(dt):
        dt = dj_timezone.make_aware(dt, dj_timezone.get_current_timezone())
    return dt


def _normalize_method(value: Any) -> str:
    method = str(value or "OTHER").strip().upper()
    return method if method in {"FP", "CARD", "FACE", "OTHER"} else "OTHER"


def _add_rejected_sample(samples: list[dict[str, Any]], *, index: int, error: str) -> None:
    if len(samples) < 20:
        samples.append({"index": index, "error": str(error)[:500]})


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

    try:
        body = request.body.decode("utf-8") if request.body else "{}"
        payload = json.loads(body or "{}")
    except Exception:
        payload = {}

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
    """
    Agent ingest raw punches — bản tối ưu batch.

    Khác bản fix transaction trước đó:
    - validate toàn bộ events trong Python;
    - pre-check duplicate bằng 2 query theo dedup_hash/device_event_id;
    - ghi dữ liệu mới bằng bulk_create(ignore_conflicts=True);
    - duplicate vẫn trả ok=true, không gây HTTP 500;
    - cursor/log cập nhật sau khi batch được duyệt xong.
    """
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return _json_error(str(_("Body JSON không hợp lệ.")), status=400)

    device_id = payload.get("device_id")
    if not device_id:
        return _json_error(str(_("Thiếu device_id.")), status=400)

    try:
        device_id_int = int(device_id)
    except Exception:
        return _json_error(str(_("device_id không hợp lệ.")), status=400)

    device = AttendanceDeviceV2.objects.filter(id=device_id_int).first()
    if not device:
        return _json_error(str(_("Không tìm thấy thiết bị.")), status=404)

    if device.assigned_agent_id != agent.id:
        return _json_error(str(_("Thiết bị không thuộc agent này.")), status=403)

    events = payload.get("events") or []
    if not isinstance(events, list):
        return _json_error(str(_("events phải là danh sách.")), status=400)

    max_batch = getattr(settings, "ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE", 2000)
    if len(events) > max_batch:
        return _json_error(str(_("Batch quá lớn.")), status=413, max_batch=max_batch)

    batch_id = str(payload.get("batch_id") or "").strip()[:64]
    cursor = payload.get("cursor") if isinstance(payload.get("cursor"), dict) else None

    started_at = dj_timezone.now()
    log = AttendanceIngestLogV2.objects.create(
        device=device,
        agent=agent,
        started_at=started_at,
        success=False,
    )

    rejected = 0
    rejected_samples: list[dict[str, Any]] = []

    # valid_rows chứa tuple đã parse: (idx, raw_obj, device_event_id, dedup_hash)
    valid_rows: list[tuple[int, AttendanceRawPunchV2, str | None, str]] = []

    # Dedupe ngay trong cùng payload để tránh tự conflict trong bulk_create.
    seen_device_event_ids: set[str] = set()
    seen_dedup_hashes: set[str] = set()
    duplicate_in_payload = 0

    now_for_rows = dj_timezone.now()

    for idx, e in enumerate(events):
        if not isinstance(e, dict):
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error="event không phải object")
            continue

        try:
            device_user_id = str(e.get("device_user_id") or "").strip()
            if not device_user_id:
                rejected += 1
                _add_rejected_sample(rejected_samples, index=idx, error="thiếu device_user_id")
                continue

            event_time_local_s = str(e.get("event_time_local") or "").strip()
            event_time_utc_s = str(e.get("event_time_utc") or "").strip()
            if not event_time_local_s or not event_time_utc_s:
                rejected += 1
                _add_rejected_sample(rejected_samples, index=idx, error="thiếu event_time_local hoặc event_time_utc")
                continue

            event_time_local = _parse_dt(event_time_local_s)
            event_time_utc = _parse_dt(event_time_utc_s)
            method = _normalize_method(e.get("method"))

            device_event_id = e.get("device_event_id")
            if device_event_id is not None:
                device_event_id = str(device_event_id).strip() or None

            dedup_hash = str(e.get("dedup_hash") or "").strip()
            if not dedup_hash:
                dedup_hash = AttendanceRawPunchV2.compute_dedup_hash(
                    device_id=device.id,
                    device_user_id=device_user_id,
                    event_time_local_iso=event_time_local_s,
                    method=method,
                )

            # Duplicate trong chính batch agent gửi: tính là duplicate mềm.
            if device_event_id and device_event_id in seen_device_event_ids:
                duplicate_in_payload += 1
                continue
            if dedup_hash in seen_dedup_hashes:
                duplicate_in_payload += 1
                continue

            if device_event_id:
                seen_device_event_ids.add(device_event_id)
            seen_dedup_hashes.add(dedup_hash)

            meta = e.get("meta")
            meta_json = meta if isinstance(meta, (dict, list)) else None

            obj = AttendanceRawPunchV2(
                device=device,
                agent=agent,
                batch_id=batch_id,
                device_user_id=device_user_id,
                event_time_local=event_time_local,
                event_time_utc=event_time_utc,
                method=method,
                device_event_id=device_event_id,
                dedup_hash=dedup_hash,
                meta_json=meta_json,
                ingested_at=now_for_rows,
            )
            valid_rows.append((idx, obj, device_event_id, dedup_hash))

        except Exception as exc:
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error=str(exc))
            continue

    processed = 0
    duplicates = duplicate_in_payload

    try:
        if valid_rows:
            device_event_ids = [x[2] for x in valid_rows if x[2]]
            dedup_hashes = [x[3] for x in valid_rows]

            existing_event_ids = set()
            if device_event_ids:
                existing_event_ids = set(
                    AttendanceRawPunchV2.objects.filter(
                        device=device,
                        device_event_id__in=device_event_ids,
                    ).values_list("device_event_id", flat=True)
                )

            existing_hashes = set(
                AttendanceRawPunchV2.objects.filter(
                    device=device,
                    dedup_hash__in=dedup_hashes,
                ).values_list("dedup_hash", flat=True)
            )

            to_create: list[AttendanceRawPunchV2] = []
            for _idx, obj, device_event_id, dedup_hash in valid_rows:
                if device_event_id and device_event_id in existing_event_ids:
                    duplicates += 1
                    continue
                if dedup_hash in existing_hashes:
                    duplicates += 1
                    continue
                to_create.append(obj)

            if to_create:
                # ignore_conflicts=True xử lý race condition nếu batch khác vừa insert cùng key.
                before_count = AttendanceRawPunchV2.objects.filter(device=device).count()
                AttendanceRawPunchV2.objects.bulk_create(
                    to_create,
                    batch_size=1000,
                    ignore_conflicts=True,
                )
                after_count = AttendanceRawPunchV2.objects.filter(device=device).count()
                processed = max(0, after_count - before_count)

                # Nếu có race condition/unique conflict trong lúc bulk_create, phần còn lại tính duplicate mềm.
                duplicates += max(0, len(to_create) - processed)

        finished_at = dj_timezone.now()
        error_message = ""
        if rejected_samples:
            error_message = json.dumps(rejected_samples, ensure_ascii=False)

        with transaction.atomic():
            if cursor is not None:
                device.last_cursor_json = cursor
            device.last_pull_at = finished_at
            device.status = AttendanceDeviceV2.Status.ONLINE
            if cursor is not None:
                device.save(update_fields=["last_cursor_json", "last_pull_at", "status"])
            else:
                device.save(update_fields=["last_pull_at", "status"])

            log.processed = processed
            log.duplicates = duplicates
            log.rejected = rejected
            log.success = True
            log.error_message = error_message
            log.accepted_cursor_snapshot = cursor if cursor is not None else None
            log.finished_at = finished_at
            log.save(update_fields=[
                "processed", "duplicates", "rejected", "success", "error_message",
                "accepted_cursor_snapshot", "finished_at",
            ])

    except Exception as ex:
        try:
            log.processed = processed
            log.duplicates = duplicates
            log.rejected = rejected
            log.success = False
            log.error_message = str(ex)
            log.finished_at = dj_timezone.now()
            log.save(update_fields=["processed", "duplicates", "rejected", "success", "error_message", "finished_at"])
        except Exception:
            pass
        return _json_error(str(_("Lỗi ingest.")), status=500)

    return JsonResponse({
        "ok": True,
        "processed": processed,
        "duplicates": duplicates,
        "rejected": rejected,
        "accepted_cursor": cursor,
        "ingest_log_id": log.id,
    })
