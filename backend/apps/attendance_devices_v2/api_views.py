from __future__ import annotations

import hashlib
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

from .sync_policy import get_device_sync_policy
from .models import (
    AttendanceDeviceAPIKeyV2,
    AttendanceDeviceAgentV2,
    AttendanceDeviceV2,
    AttendanceIngestLogV2,
    AttendanceRawPunchV2,
    AttendanceDeviceStatusReportV2,
    AttendanceDeviceBackfillReportV2,
    AttendanceDeviceTimeSyncReportV2,
)


# =========================
# Helpers: response/auth
# =========================

def _json_error(message: str, status: int = 400, **extra: Any) -> JsonResponse:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _json_ok(**extra: Any) -> JsonResponse:
    payload = {"ok": True, "error": None}
    payload.update(extra)
    return JsonResponse(payload)


def _get_bearer_token(request: HttpRequest) -> str | None:
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
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


# =========================
# Helpers: parse/normalize
# =========================

def _parse_json_body(request: HttpRequest) -> dict[str, Any] | JsonResponse:
    try:
        if not request.body:
            return {}
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return _json_error(str(_("Body JSON không hợp lệ.")), status=400)
    if not isinstance(payload, dict):
        return _json_error(str(_("Body JSON phải là object.")), status=400)
    return payload


def _parse_dt(value: Any) -> datetime:
    """
    Parse datetime ISO-8601 từ Agent V2.

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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_dt_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return _parse_dt(value)
    except Exception:
        return None


def _normalize_realtime_status(value: Any) -> str:
    status = str(value or "ONLINE").strip().upper()
    valid = {choice[0] for choice in AttendanceDeviceStatusReportV2.RealtimeStatus.choices}
    return status if status in valid else AttendanceDeviceStatusReportV2.RealtimeStatus.ERROR


def _normalize_backfill_status(value: Any) -> str:
    status = str(value or "SUCCESS").strip().upper()
    valid = {choice[0] for choice in AttendanceDeviceBackfillReportV2.Status.choices}
    return status if status in valid else AttendanceDeviceBackfillReportV2.Status.FAILED

def _normalize_time_sync_state(value: Any) -> str:
    status = str(value or "NOT_CHECKED").strip().upper()
    valid = {choice[0] for choice in AttendanceDeviceStatusReportV2.TimeSyncState.choices}
    return status if status in valid else AttendanceDeviceStatusReportV2.TimeSyncState.FAILED


def _normalize_time_sync_report_status(value: Any) -> str:
    status = str(value or "FAILED").strip().upper()
    valid = {choice[0] for choice in AttendanceDeviceTimeSyncReportV2.Status.choices}
    return status if status in valid else AttendanceDeviceTimeSyncReportV2.Status.FAILED


def _merge_device_cursor(device: AttendanceDeviceV2, patch: dict[str, Any]) -> dict[str, Any]:
    base = device.last_cursor_json if isinstance(device.last_cursor_json, dict) else {}
    merged = dict(base)
    merged.update({k: v for k, v in patch.items() if v is not None})
    return merged


def _device_status_from_realtime(status: str) -> str:
    if status == AttendanceDeviceStatusReportV2.RealtimeStatus.ONLINE:
        return AttendanceDeviceV2.Status.ONLINE
    if status in {
        AttendanceDeviceStatusReportV2.RealtimeStatus.OFFLINE,
        AttendanceDeviceStatusReportV2.RealtimeStatus.ERROR,
        AttendanceDeviceStatusReportV2.RealtimeStatus.REALTIME_UNAVAILABLE,
    }:
        return AttendanceDeviceV2.Status.OFFLINE
    return AttendanceDeviceV2.Status.UNKNOWN


def _serialize_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None




def _add_rejected_sample(samples: list[dict[str, Any]], *, index: int, error: str) -> None:
    if len(samples) < 20:
        samples.append({"index": index, "error": str(error)[:500]})


def _device_config_version(devices: list[AttendanceDeviceV2]) -> str:
    """
    Tạo phiên bản ổn định cho snapshot cấu hình Agent.

    Chỉ dùng các trường cấu hình; không dùng status/cursor/last_pull_at để tránh
    config_version thay đổi theo mỗi lượt chấm công hoặc status report.
    """
    rows = [
        {
            "id": d.id,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "is_active": d.is_active,
            "assigned_agent_id": d.assigned_agent_id,
        }
        for d in devices
    ]
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _device_json(device: AttendanceDeviceV2) -> dict[str, Any]:
    profile = device.sdk_profile if isinstance(device.sdk_profile, dict) else {}
    return {
        "id": device.id,
        "name": device.name,
        "brand": device.brand,
        "model": device.model,
        "serial_no": device.serial_no,
        "host": device.host,
        "port": device.port,
        "timezone": device.timezone,
        "connect_mode": device.connect_mode,
        "is_active": device.is_active,
        "status": device.status,
        "last_cursor_json": device.last_cursor_json or {},
        "last_pull_at": device.last_pull_at.isoformat() if device.last_pull_at else None,
        "sdk_profile": profile,
        "sync_policy": get_device_sync_policy(device),
    }


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

    payload = _parse_json_body(request)
    if isinstance(payload, JsonResponse):
        # Heartbeat lỗi JSON là lỗi client, nhưng vẫn trả rõ ràng theo contract mới.
        return payload

    now = dj_timezone.now()
    AttendanceDeviceAgentV2.objects.filter(id=agent.id).update(
        last_seen_at=now,
        hostname=payload.get("hostname", agent.hostname) or agent.hostname,
        ip_address=payload.get("ip", agent.ip_address) or agent.ip_address,
        version=payload.get("version", agent.version) or agent.version,
    )

    return _json_ok(server_time=now.isoformat())


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

    # Trả cả thiết bị inactive đang được gán. Agent cần thấy is_active=false
    # để dừng listener/health-check/reconnect mà không phải restart Service.
    devices = list(
        AttendanceDeviceV2.objects
        .filter(assigned_agent_id=agent.id)
        .order_by("name", "id")
    )
    now = dj_timezone.now()

    return _json_ok(
        server_time=now.isoformat(),
        config_version=_device_config_version(devices),
        devices=[_device_json(d) for d in devices],
    )


# =========================
# API: Ingest raw punches
# =========================

@csrf_exempt
@require_POST
def raw_punches_batch(request: HttpRequest) -> JsonResponse:
    """
    Agent V2 ingest raw punches.

    Dùng cho cả REALTIME và BACKFILL:
    - validate toàn bộ events trong Python;
    - duplicate trong payload/DB là duplicate mềm, vẫn ok=true;
    - bulk_create(ignore_conflicts=True) để chịu retry/backfill;
    - cursor/status JSON Agent gửi lên được lưu nguyên trạng vào device.last_cursor_json.
    """
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    payload = _parse_json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

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

    max_batch = int(getattr(settings, "ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE", 2000))
    if len(events) > max_batch:
        return _json_error(str(_("Batch quá lớn.")), status=413, max_batch=max_batch)

    batch_id = str(payload.get("batch_id") or "").strip()[:64]
    cursor = payload.get("cursor") if isinstance(payload.get("cursor"), dict) else {}

    started_at = dj_timezone.now()
    log = AttendanceIngestLogV2.objects.create(
        device=device,
        agent=agent,
        started_at=started_at,
        success=False,
    )

    rejected = 0
    rejected_samples: list[dict[str, Any]] = []
    valid_rows: list[tuple[int, AttendanceRawPunchV2, str | None, str]] = []

    # Dedupe ngay trong payload để tránh tự conflict trong bulk_create.
    seen_device_event_ids: set[str] = set()
    seen_dedup_hashes: set[str] = set()
    duplicate_in_payload = 0
    now_for_rows = dj_timezone.now()

    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error="event không phải object")
            continue

        try:
            device_user_id = str(event.get("device_user_id") or "").strip()
            if not device_user_id:
                rejected += 1
                _add_rejected_sample(rejected_samples, index=idx, error="thiếu device_user_id")
                continue

            event_time_local_s = str(event.get("event_time_local") or "").strip()
            event_time_utc_s = str(event.get("event_time_utc") or "").strip()
            if not event_time_local_s or not event_time_utc_s:
                rejected += 1
                _add_rejected_sample(rejected_samples, index=idx, error="thiếu event_time_local hoặc event_time_utc")
                continue

            event_time_local = _parse_dt(event_time_local_s)
            event_time_utc = _parse_dt(event_time_utc_s)
            method = _normalize_method(event.get("method"))

            device_event_id = event.get("device_event_id")
            if device_event_id is not None:
                device_event_id = str(device_event_id).strip() or None

            dedup_hash = str(event.get("dedup_hash") or "").strip()
            if not dedup_hash:
                dedup_hash = AttendanceRawPunchV2.compute_dedup_hash(
                    device_id=device.id,
                    device_user_id=device_user_id,
                    event_time_local_iso=event_time_local_s,
                    method=method,
                )

            if device_event_id and device_event_id in seen_device_event_ids:
                duplicate_in_payload += 1
                continue
            if dedup_hash in seen_dedup_hashes:
                duplicate_in_payload += 1
                continue

            if device_event_id:
                seen_device_event_ids.add(device_event_id)
            seen_dedup_hashes.add(dedup_hash)

            meta = event.get("meta")
            meta_json = meta if isinstance(meta, (dict, list)) else None

            raw = AttendanceRawPunchV2(
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
            valid_rows.append((idx, raw, device_event_id, dedup_hash))
        except Exception as exc:
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error=str(exc))

    processed = 0
    duplicates = duplicate_in_payload

    try:
        if valid_rows:
            device_event_ids = [row[2] for row in valid_rows if row[2]]
            dedup_hashes = [row[3] for row in valid_rows]

            existing_event_ids: set[str] = set()
            if device_event_ids:
                existing_event_ids = set(
                    AttendanceRawPunchV2.objects
                    .filter(device=device, device_event_id__in=device_event_ids)
                    .values_list("device_event_id", flat=True)
                )

            existing_hashes = set(
                AttendanceRawPunchV2.objects
                .filter(device=device, dedup_hash__in=dedup_hashes)
                .values_list("dedup_hash", flat=True)
            )

            to_create: list[AttendanceRawPunchV2] = []
            for _idx, raw, device_event_id, dedup_hash in valid_rows:
                if device_event_id and device_event_id in existing_event_ids:
                    duplicates += 1
                    continue
                if dedup_hash in existing_hashes:
                    duplicates += 1
                    continue
                to_create.append(raw)

            if to_create:
                AttendanceRawPunchV2.objects.bulk_create(
                    to_create,
                    batch_size=1000,
                    ignore_conflicts=True,
                )
                # Với pre-check duplicate ở trên, đây là số dự kiến ghi mới.
                # Nếu có race condition cùng lúc insert trùng, ignore_conflicts vẫn đảm bảo không lỗi;
                # sai lệch processed hiếm và không ảnh hưởng nghiệp vụ/idempotency.
                processed = len(to_create)

        finished_at = dj_timezone.now()
        error_message = ""
        if rejected_samples:
            error_message = json.dumps(rejected_samples, ensure_ascii=False)

        with transaction.atomic():
            device.last_cursor_json = cursor
            device.last_pull_at = finished_at
            device.status = AttendanceDeviceV2.Status.ONLINE
            device.save(update_fields=["last_cursor_json", "last_pull_at", "status"])

            log.processed = processed
            log.duplicates = duplicates
            log.rejected = rejected
            log.success = True
            log.error_message = error_message
            log.accepted_cursor_snapshot = cursor
            log.finished_at = finished_at
            log.save(update_fields=[
                "processed", "duplicates", "rejected", "success", "error_message",
                "accepted_cursor_snapshot", "finished_at",
            ])

    except Exception as exc:
        try:
            log.processed = processed
            log.duplicates = duplicates
            log.rejected = rejected
            log.success = False
            log.error_message = str(exc)
            log.finished_at = dj_timezone.now()
            log.save(update_fields=["processed", "duplicates", "rejected", "success", "error_message", "finished_at"])
        except Exception:
            pass
        return _json_error(str(_("Lỗi ingest.")), status=500)

    return _json_ok(
        processed=processed,
        duplicates=duplicates,
        rejected=rejected,
        ingest_log_id=log.id,
        accepted_cursor=cursor,
    )

# =========================
# API: Device realtime/status report
# =========================

@csrf_exempt
@require_POST
def agent_device_status(request: HttpRequest, agent_id: int) -> JsonResponse:
    """
    Agent V2 gửi trạng thái realtime/health-check của các thiết bị.

    Payload:
    {
      "devices": [
        {
          "device_id": 1,
          "realtime_status": "ONLINE",
          "last_realtime_at": "...",
          "last_event_time_local": "...",
          "last_device_seen_at": "...",
          "pending_backfill_required": false,
          "drift_seconds": 1,
          "last_error": null
        }
      ]
    }
    """
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    err = _require_same_agent(agent, agent_id)
    if err:
        return err

    payload = _parse_json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

    items = payload.get("devices")
    if items is None and "device_id" in payload:
        items = [payload]
    if not isinstance(items, list):
        return _json_error(str(_("devices phải là danh sách.")), status=400)

    max_items = int(getattr(settings, "ATTENDANCE_DEVICE_STATUS_MAX_ITEMS", 200))
    if len(items) > max_items:
        return _json_error(str(_("Device status batch quá lớn.")), status=413, max_items=max_items)

    now = dj_timezone.now()
    received = 0
    rejected = 0
    rejected_samples: list[dict[str, Any]] = []
    reports: list[AttendanceDeviceStatusReportV2] = []
    device_updates: dict[int, dict[str, Any]] = {}

    device_ids: list[int] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error="item không phải object")
            continue
        did = _safe_int(item.get("device_id"), 0)
        if did <= 0:
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error="thiếu hoặc sai device_id")
            continue
        device_ids.append(did)

    devices = {
        d.id: d
        for d in AttendanceDeviceV2.objects.filter(id__in=device_ids, assigned_agent_id=agent.id)
    }

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        did = _safe_int(item.get("device_id"), 0)
        if did <= 0:
            continue
        device = devices.get(did)
        if not device:
            rejected += 1
            _add_rejected_sample(rejected_samples, index=idx, error=f"device_id {did} không thuộc agent")
            continue

        status = _normalize_realtime_status(item.get("realtime_status"))
        last_realtime_at = _parse_dt_or_none(item.get("last_realtime_at"))
        last_event_time_local = _parse_dt_or_none(item.get("last_event_time_local"))
        last_device_seen_at = _parse_dt_or_none(item.get("last_device_seen_at")) or last_realtime_at or now
        drift_seconds = item.get("drift_seconds")
        drift_seconds = None if drift_seconds in (None, "") else _safe_int(drift_seconds, 0)
        pending_backfill_required = _safe_bool(item.get("pending_backfill_required"), False)
        last_error = str(item.get("last_error") or "")[:4000]
        time_sync_enabled = _safe_bool(item.get("time_sync_enabled"), False)
        time_sync_state = _normalize_time_sync_state(item.get("time_sync_state"))
        last_time_check_at = _parse_dt_or_none(item.get("last_time_check_at"))
        device_time_at_check = _parse_dt_or_none(item.get("device_time_at_check"))
        last_time_sync_attempt_at = _parse_dt_or_none(item.get("last_time_sync_attempt_at"))
        last_time_sync_success_at = _parse_dt_or_none(item.get("last_time_sync_success_at"))
        last_time_sync_status = str(item.get("last_time_sync_status") or "")[:32]
        last_time_sync_before_drift_seconds = item.get("last_time_sync_before_drift_seconds")
        last_time_sync_before_drift_seconds = None if last_time_sync_before_drift_seconds in (None, "") else _safe_int(last_time_sync_before_drift_seconds, 0)
        last_time_sync_after_drift_seconds = item.get("last_time_sync_after_drift_seconds")
        last_time_sync_after_drift_seconds = None if last_time_sync_after_drift_seconds in (None, "") else _safe_int(last_time_sync_after_drift_seconds, 0)
        last_time_sync_error = str(item.get("last_time_sync_error") or "")[:4000]
        agent_config_version = str(item.get("agent_config_version") or "")[:128]

        reports.append(AttendanceDeviceStatusReportV2(
            device=device,
            agent=agent,
            realtime_status=status,
            last_realtime_at=last_realtime_at,
            last_event_time_local=last_event_time_local,
            last_device_seen_at=last_device_seen_at,
            pending_backfill_required=pending_backfill_required,
            drift_seconds=drift_seconds,
            time_sync_enabled=time_sync_enabled,
            time_sync_state=time_sync_state,
            last_time_check_at=last_time_check_at,
            device_time_at_check=device_time_at_check,
            last_time_sync_attempt_at=last_time_sync_attempt_at,
            last_time_sync_success_at=last_time_sync_success_at,
            last_time_sync_status=last_time_sync_status,
            last_time_sync_before_drift_seconds=last_time_sync_before_drift_seconds,
            last_time_sync_after_drift_seconds=last_time_sync_after_drift_seconds,
            last_time_sync_error=last_time_sync_error,
            agent_config_version=agent_config_version,
            last_error=last_error,
            payload_json=item,
            reported_at=now,
        ))
        received += 1

        cursor_patch = {
            "mode": "REALTIME_PLUS_BACKFILL",
            "last_device_status_report_at": now.isoformat(),
            "realtime_status": status,
            "last_realtime_at": item.get("last_realtime_at"),
            "last_event_time_local": item.get("last_event_time_local"),
            "last_device_seen_at": item.get("last_device_seen_at"),
            "pending_backfill_required": pending_backfill_required,
            "drift_seconds": drift_seconds,
            "time_sync_enabled": time_sync_enabled,
            "time_sync_state": time_sync_state,
            "last_time_check_at": item.get("last_time_check_at"),
            "device_time_at_check": item.get("device_time_at_check"),
            "last_time_sync_attempt_at": item.get("last_time_sync_attempt_at"),
            "last_time_sync_success_at": item.get("last_time_sync_success_at"),
            "last_time_sync_status": last_time_sync_status,
            "last_time_sync_before_drift_seconds": last_time_sync_before_drift_seconds,
            "last_time_sync_after_drift_seconds": last_time_sync_after_drift_seconds,
            "last_time_sync_error": last_time_sync_error,
            "agent_config_version": agent_config_version,
            "last_realtime_error": last_error,
        }
        device_updates[device.id] = {
            "cursor": _merge_device_cursor(device, cursor_patch),
            "status": _device_status_from_realtime(status),
            "last_seen": last_device_seen_at,
        }

    if reports:
        AttendanceDeviceStatusReportV2.objects.bulk_create(reports, batch_size=500)

    # Update snapshot trạng thái gọn cho các màn cũ.
    # Không ghi last_pull_at ở đây: last_pull_at chỉ dành cho lần thực sự ingest/pull raw.
    for did, upd in device_updates.items():
        AttendanceDeviceV2.objects.filter(id=did).update(
            last_cursor_json=upd["cursor"],
            status=upd["status"],
        )

    return _json_ok(received=received, rejected=rejected, rejected_samples=rejected_samples)


# =========================
# API: Backfill report
# =========================

@csrf_exempt
@require_POST
def agent_backfill_report(request: HttpRequest, agent_id: int) -> JsonResponse:
    """
    Agent V2 gửi kết quả chạy backfill theo từng device/window.
    """
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    err = _require_same_agent(agent, agent_id)
    if err:
        return err

    payload = _parse_json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

    device_id = _safe_int(payload.get("device_id"), 0)
    if device_id <= 0:
        return _json_error(str(_("Thiếu hoặc sai device_id.")), status=400)

    device = AttendanceDeviceV2.objects.filter(id=device_id, assigned_agent_id=agent.id).first()
    if not device:
        return _json_error(str(_("Thiết bị không thuộc agent này.")), status=403)

    now = dj_timezone.now()
    status = _normalize_backfill_status(payload.get("status"))
    started_at = _parse_dt_or_none(payload.get("started_at"))
    finished_at = _parse_dt_or_none(payload.get("finished_at")) or now
    from_local = _parse_dt_or_none(payload.get("from_local"))
    to_local = _parse_dt_or_none(payload.get("to_local"))

    report = AttendanceDeviceBackfillReportV2.objects.create(
        device=device,
        agent=agent,
        window_name=str(payload.get("window_name") or "")[:64],
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=None if payload.get("duration_seconds") in (None, "") else _safe_int(payload.get("duration_seconds"), 0),
        days=max(_safe_int(payload.get("days"), 0), 0),
        from_local=from_local,
        to_local=to_local,
        read_total=max(_safe_int(payload.get("read_total"), 0), 0),
        filtered=max(_safe_int(payload.get("filtered"), 0), 0),
        sent_batches=max(_safe_int(payload.get("sent_batches"), 0), 0),
        pending_batches=max(_safe_int(payload.get("pending_batches"), 0), 0),
        processed=max(_safe_int(payload.get("processed"), 0), 0),
        duplicates=max(_safe_int(payload.get("duplicates"), 0), 0),
        rejected=max(_safe_int(payload.get("rejected"), 0), 0),
        errors=max(_safe_int(payload.get("errors"), 0), 0),
        error_code=str(payload.get("error_code") or "")[:64],
        error_message=str(payload.get("error_message") or "")[:4000],
        need_retry=_safe_bool(payload.get("need_retry"), False),
        need_backfill=_safe_bool(payload.get("need_backfill"), False),
        payload_json=payload,
        reported_at=now,
    )

    cursor_patch = {
        "mode": "REALTIME_PLUS_BACKFILL",
        "last_backfill_report_at": now.isoformat(),
        "last_backfill_status": status,
        "last_backfill_window": report.window_name,
        "last_backfill_at": _serialize_dt(finished_at),
        "last_backfill_from": payload.get("from_local"),
        "last_backfill_to": payload.get("to_local"),
        "last_backfill_read_total": report.read_total,
        "last_backfill_filtered": report.filtered,
        "last_backfill_processed": report.processed,
        "last_backfill_duplicates": report.duplicates,
        "last_backfill_rejected": report.rejected,
        "last_backfill_pending_batches": report.pending_batches,
        "last_backfill_error_code": report.error_code,
        "last_backfill_error": report.error_message,
        "pending_backfill_required": report.need_backfill,
    }
    device.last_cursor_json = _merge_device_cursor(device, cursor_patch)
    device.save(update_fields=["last_cursor_json"])

    return _json_ok(backfill_report_id=report.id)

# =========================
# API: Time sync report
# =========================

@csrf_exempt
@require_POST
def agent_time_sync_report(request: HttpRequest, agent_id: int) -> JsonResponse:
    """Agent gửi kết quả một lần thực sự thử đồng bộ thời gian thiết bị."""
    agent = _auth_agent(request)
    if isinstance(agent, JsonResponse):
        return agent

    err = _require_same_agent(agent, agent_id)
    if err:
        return err

    payload = _parse_json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

    device_id = _safe_int(payload.get("device_id"), 0)
    if device_id <= 0:
        return _json_error(str(_("Thiếu hoặc sai device_id.")), status=400)

    device = AttendanceDeviceV2.objects.filter(id=device_id, assigned_agent_id=agent.id).first()
    if not device:
        return _json_error(str(_("Thiết bị không thuộc agent này.")), status=403)

    now = dj_timezone.now()
    status = _normalize_time_sync_report_status(payload.get("status"))
    report = AttendanceDeviceTimeSyncReportV2.objects.create(
        device=device,
        agent=agent,
        run_id=str(payload.get("run_id") or "")[:160],
        window_key=str(payload.get("window_key") or "")[:64],
        attempt_no=max(_safe_int(payload.get("attempt_no"), 1), 1),
        status=status,
        started_at=_parse_dt_or_none(payload.get("started_at")),
        finished_at=_parse_dt_or_none(payload.get("finished_at")) or now,
        agent_time_before=_parse_dt_or_none(payload.get("agent_time_before")),
        device_time_before=_parse_dt_or_none(payload.get("device_time_before")),
        agent_time_after=_parse_dt_or_none(payload.get("agent_time_after")),
        device_time_after=_parse_dt_or_none(payload.get("device_time_after")),
        before_drift_seconds=None if payload.get("before_drift_seconds") in (None, "") else _safe_int(payload.get("before_drift_seconds"), 0),
        after_drift_seconds=None if payload.get("after_drift_seconds") in (None, "") else _safe_int(payload.get("after_drift_seconds"), 0),
        error_code=str(payload.get("error_code") or "")[:64],
        error_message=str(payload.get("error_message") or "")[:4000],
        payload_json=payload,
        reported_at=now,
    )

    cursor_patch = {
        "last_time_sync_report_at": now.isoformat(),
        "last_time_sync_status": status,
        "last_time_sync_attempt_at": payload.get("started_at"),
        "last_time_sync_success_at": payload.get("finished_at") if status == AttendanceDeviceTimeSyncReportV2.Status.SUCCESS else None,
        "last_time_sync_before_drift_seconds": report.before_drift_seconds,
        "last_time_sync_after_drift_seconds": report.after_drift_seconds,
        "last_time_sync_error": report.error_message,
    }
    device.last_cursor_json = _merge_device_cursor(device, cursor_patch)
    device.save(update_fields=["last_cursor_json"])

    return _json_ok(time_sync_report_id=report.id, received=1, rejected=0)

