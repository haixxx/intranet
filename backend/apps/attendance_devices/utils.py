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


def verify_hmac_signature(body_bytes:  bytes, client_id: str, timestamp_str: str, signature_hex: str) -> None:
    import logging
    logger = logging.getLogger(__name__)
    
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
    
    # DEBUG LOGGING
    logger.warning("========== HMAC VERIFY DEBUG ==========")
    logger.warning(f"Client ID: {client_id}")
    logger.warning(f"Secret: {secret}")
    logger.warning(f"Timestamp (request): {ts}")
    logger.warning(f"Timestamp (server): {now}")
    logger.warning(f"Difference: {abs(now - ts)} seconds")
    logger.warning(f"Window: {window_sec} seconds")
    logger.warning(f"Timestamp valid: {abs(now - ts) <= window_sec}")
    
    if abs(now - ts) > window_sec:
        logger.error(f"TIMESTAMP WINDOW EXCEEDED: {abs(now - ts)} > {window_sec}")
        raise HMACAuthError("Timestamp window exceeded.")

    # DEBUG:  Show body
    logger.warning(f"Body length: {len(body_bytes)} bytes")
    logger.warning(f"Body (first 200): {body_bytes[:200]}")
    logger.warning(f"Body (last 50): {body_bytes[-50:]}")
    
    # Compute signature
    msg = body_bytes + timestamp_str.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    
    logger.warning(f"Signature (received): {signature_hex}")
    logger.warning(f"Signature (computed): {expected}")
    logger.warning(f"Signature match: {hmac.compare_digest(expected, signature_hex)}")
    logger.warning("========================================")
    
    if not hmac.compare_digest(expected, signature_hex):
        logger.error("SIGNATURE MISMATCH!")
        raise HMACAuthError("Signature mismatch.")