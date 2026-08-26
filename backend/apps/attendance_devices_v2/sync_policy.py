from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


POLICY_VERSION = 3
BACKFILL_RUN_MODE_ALWAYS = "ALWAYS"
BACKFILL_RUN_MODE_IF_NEEDED = "IF_NEEDED"
BACKFILL_RUN_MODE_CHOICES = {
    BACKFILL_RUN_MODE_ALWAYS,
    BACKFILL_RUN_MODE_IF_NEEDED,
}

DEFAULT_SYNC_POLICY: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "realtime_enabled": True,
    "backfill_enabled": True,
    "backfill_mode": "SEQUENTIAL",
    "backfill_windows": [
        {
            "name": "morning-check",
            "time": "07:30",
            "days": 1,
            "run_mode": BACKFILL_RUN_MODE_IF_NEEDED,
            "grace_minutes": 60,
            "enabled": True,
        },
        {
            "name": "midday-check",
            "time": "13:20",
            "days": 1,
            "run_mode": BACKFILL_RUN_MODE_IF_NEEDED,
            "grace_minutes": 60,
            "enabled": True,
        },
        {
            "name": "nightly",
            "time": "22:00",
            "days": 15,
            "run_mode": BACKFILL_RUN_MODE_ALWAYS,
            "grace_minutes": 120,
            "enabled": True,
        },
    ],
    "backfill_retry_enabled": True,
    "backfill_retry_delay_minutes": 15,
    "backfill_max_retries_per_window": 3,
    "backfill_retry_on_device_offline": True,
    "backfill_retry_on_server_error": False,
    "time_sync_enabled": False,
    "time_sync_warn_seconds": 120,
    "time_sync_auto_seconds": 300,
    "time_sync_allowed_windows": [
        {"from": "22:00", "to": "23:30"},
    ],
    "time_sync_check_seconds": 600,
    "time_sync_max_retries_per_window": 2,
    "time_sync_retry_delay_minutes": 15,
    "time_sync_verify_tolerance_seconds": 30,
    "health_check_seconds": 10,
    "reconnect_seconds": 30,
    "missed_schedule_grace_minutes": 60,
}


def get_default_sync_policy() -> dict[str, Any]:
    return deepcopy(DEFAULT_SYNC_POLICY)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _valid_clock(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.strptime(text, "%H:%M")
        return text
    except (TypeError, ValueError):
        return fallback


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(parsed, maximum))


def _normalize_backfill_windows(raw_windows: Any) -> list[dict[str, Any]]:
    defaults = {
        item["name"]: deepcopy(item)
        for item in DEFAULT_SYNC_POLICY["backfill_windows"]
    }
    incoming: dict[str, dict[str, Any]] = {}

    if isinstance(raw_windows, list):
        legacy_candidates: list[dict[str, Any]] = []
        for item in raw_windows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if name in defaults:
                incoming[name] = item
            else:
                legacy_candidates.append(item)

        # Policy rất cũ có thể chỉ chứa một window không có name. Giữ lại
        # cấu hình đó như nightly thay vì âm thầm trả về 22:00/15 ngày.
        if "nightly" not in incoming and len(raw_windows) == 1 and legacy_candidates:
            incoming["nightly"] = legacy_candidates[0]

    normalized: list[dict[str, Any]] = []
    for name in ("morning-check", "midday-check", "nightly"):
        default = defaults[name]
        source = incoming.get(name, {})
        run_mode = str(source.get("run_mode") or default["run_mode"]).strip().upper()
        if run_mode not in BACKFILL_RUN_MODE_CHOICES:
            run_mode = default["run_mode"]

        normalized.append(
            {
                "name": name,
                "time": _valid_clock(source.get("time"), default["time"]),
                "days": _bounded_int(source.get("days"), default["days"], 1, 60),
                "run_mode": run_mode,
                "grace_minutes": _bounded_int(
                    source.get("grace_minutes"),
                    default["grace_minutes"],
                    1,
                    360,
                ),
                "enabled": bool(source.get("enabled", default["enabled"])),
            }
        )

    return normalized


def normalize_sync_policy(raw_policy: Any) -> dict[str, Any]:
    raw = raw_policy if isinstance(raw_policy, dict) else {}
    result = _deep_merge(DEFAULT_SYNC_POLICY, raw)
    result["policy_version"] = POLICY_VERSION
    result["backfill_windows"] = _normalize_backfill_windows(raw.get("backfill_windows"))

    result["realtime_enabled"] = bool(result.get("realtime_enabled", True))
    result["backfill_enabled"] = bool(result.get("backfill_enabled", True))
    result["backfill_mode"] = "SEQUENTIAL"
    result["backfill_retry_enabled"] = bool(result.get("backfill_retry_enabled", True))
    result["backfill_retry_delay_minutes"] = _bounded_int(
        result.get("backfill_retry_delay_minutes"), 15, 1, 240
    )
    result["backfill_max_retries_per_window"] = _bounded_int(
        result.get("backfill_max_retries_per_window"), 3, 1, 20
    )
    result["backfill_retry_on_device_offline"] = bool(
        result.get("backfill_retry_on_device_offline", True)
    )
    result["backfill_retry_on_server_error"] = bool(
        result.get("backfill_retry_on_server_error", False)
    )

    result["time_sync_enabled"] = bool(result.get("time_sync_enabled", False))
    result["time_sync_warn_seconds"] = _bounded_int(
        result.get("time_sync_warn_seconds"), 120, 10, 86400
    )
    result["time_sync_auto_seconds"] = _bounded_int(
        result.get("time_sync_auto_seconds"), 300, 30, 86400
    )
    if result["time_sync_auto_seconds"] < result["time_sync_warn_seconds"]:
        result["time_sync_auto_seconds"] = result["time_sync_warn_seconds"]

    allowed = result.get("time_sync_allowed_windows")
    allowed_first = allowed[0] if isinstance(allowed, list) and allowed and isinstance(allowed[0], dict) else {}
    result["time_sync_allowed_windows"] = [
        {
            "from": _valid_clock(allowed_first.get("from"), "22:00"),
            "to": _valid_clock(allowed_first.get("to"), "23:30"),
        }
    ]
    result["time_sync_check_seconds"] = _bounded_int(
        result.get("time_sync_check_seconds"), 600, 60, 86400
    )
    result["time_sync_max_retries_per_window"] = _bounded_int(
        result.get("time_sync_max_retries_per_window"), 2, 1, 20
    )
    result["time_sync_retry_delay_minutes"] = _bounded_int(
        result.get("time_sync_retry_delay_minutes"), 15, 1, 240
    )
    result["time_sync_verify_tolerance_seconds"] = _bounded_int(
        result.get("time_sync_verify_tolerance_seconds"), 30, 1, 600
    )
    result["health_check_seconds"] = _bounded_int(
        result.get("health_check_seconds"), 10, 5, 300
    )
    result["reconnect_seconds"] = _bounded_int(
        result.get("reconnect_seconds"), 30, 5, 600
    )
    result["missed_schedule_grace_minutes"] = _bounded_int(
        result.get("missed_schedule_grace_minutes"), 60, 1, 360
    )
    return result


def get_device_sync_policy(device: Any) -> dict[str, Any]:
    sdk_profile = getattr(device, "sdk_profile", None) if device else None
    sdk_profile = sdk_profile if isinstance(sdk_profile, dict) else {}
    raw_policy = sdk_profile.get("sync_policy")
    return normalize_sync_policy(raw_policy)


def set_device_sync_policy(device: Any, policy: dict[str, Any]) -> None:
    sdk_profile = device.sdk_profile if isinstance(device.sdk_profile, dict) else {}
    updated = deepcopy(sdk_profile)
    updated["sync_policy"] = normalize_sync_policy(policy)
    device.sdk_profile = updated
