import hmac
import hashlib
import time
from typing import Tuple

from django.conf import settings
from django.http import HttpRequest


class HMACAuthError(Exception):
    pass


def parse_hmac_auth_header(request: HttpRequest) -> Tuple[str, str, str]:
    auth = request.headers.get("Authorization", "") or request.META.get("HTTP_AUTHORIZATION", "")
    prefix = "HMAC "
    if not auth.startswith(prefix):
        raise HMACAuthError("Missing or invalid Authorization header.")
    parts = auth[len(prefix):].split(":")
    if len(parts) != 3:
        raise HMACAuthError("Invalid HMAC header format.")
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def verify_hmac_signature(body_bytes: bytes, client_id: str, timestamp_str: str, signature_hex: str) -> None:
    clients = getattr(settings, "ATTENDANCE_INGEST_HMAC_CLIENTS", {}) or {}
    secret = clients.get(client_id)
    if not secret:
        raise HMACAuthError("Unknown client_id.")

    try:
        ts = int(timestamp_str)
    except Exception:
        raise HMACAuthError("Invalid timestamp.")

    window_sec = int(getattr(settings, "ATTENDANCE_INGEST_HMAC_WINDOW_SECONDS", 300))
    now = int(time.time())
    if abs(now - ts) > window_sec:
        raise HMACAuthError("Timestamp window exceeded.")

    msg = body_bytes + timestamp_str.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_hex):
        raise HMACAuthError("Signature mismatch.")