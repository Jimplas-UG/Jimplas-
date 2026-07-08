"""
Persist Binance API credentials across bridge restarts (encrypted at rest).
Cleared only on explicit POST /api/logout — desk app login does not disconnect.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("session_store")

_DEFAULT_PATH = Path(os.environ.get("BINANCE_SESSION_FILE", "/var/lib/bilshenz/binance-session.json"))


def _session_path() -> Path:
    return Path(os.environ.get("BINANCE_SESSION_FILE", str(_DEFAULT_PATH)))


def _sign_key() -> bytes:
    raw = (
        os.environ.get("SESSION_ENC_KEY", "").strip()
        or os.environ.get("BRIDGE_TOKEN", "").strip()
        or "bilshenz-session-v1"
    )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def save_binance_session(api_key: str, api_secret: str, testnet: bool) -> None:
    key = (api_key or "").strip()
    secret = (api_secret or "").strip()
    if not key or not secret:
        return
    payload = json.dumps(
        {"api_key": key, "api_secret": secret, "testnet": bool(testnet)},
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_sign_key(), payload, hashlib.sha256).hexdigest()
    envelope = json.dumps(
        {"v": 1, "p": base64.b64encode(payload).decode("ascii"), "s": sig},
        separators=(",", ":"),
    ).encode("utf-8")
    path = _session_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(envelope)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        log.info("Binance session persisted (%s)", path)
    except OSError as e:
        log.warning("could not persist Binance session: %s", e)


def load_binance_session() -> dict[str, Any] | None:
    path = _session_path()
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("v") != 1:
            return None
        payload_b64 = envelope.get("p", "")
        sig = envelope.get("s", "")
        payload = base64.b64decode(payload_b64)
        expected = hmac.new(_sign_key(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(sig)):
            log.warning("Binance session file signature mismatch — ignoring")
            return None
        data = json.loads(payload.decode("utf-8"))
        if not data.get("api_key") or not data.get("api_secret"):
            return None
        return data
    except Exception as e:
        log.warning("could not load Binance session: %s", e)
        return None


def clear_binance_session() -> None:
    path = _session_path()
    try:
        if path.is_file():
            path.unlink()
            log.info("Binance session cleared")
    except OSError as e:
        log.warning("could not clear Binance session: %s", e)
