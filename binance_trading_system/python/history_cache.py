"""Persist trade calendar + deal history across bridge restarts (JSON on disk)."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("history_cache")

_CACHE_VERSION = 1


def history_cache_path() -> Path:
    raw = (os.environ.get("TRADE_HISTORY_CACHE_FILE") or "").strip()
    if raw:
        return Path(raw)
    return Path("/var/lib/bilshenz/trade-history-cache.json")


def load_history_cache() -> dict[str, Any]:
    path = history_cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or int(data.get("v") or 0) != _CACHE_VERSION:
            return {}
        return data
    except Exception as e:
        log.warning("could not load trade history cache: %s", e)
        return {}


def save_history_cache(
    *,
    calendar: dict[str, Any] | None = None,
    deals: list[dict[str, Any]] | None = None,
    deal_symbols: list[str] | None = None,
) -> None:
    path = history_cache_path()
    try:
        existing = load_history_cache() if path.is_file() else {"v": _CACHE_VERSION}
        if int(existing.get("v") or 0) != _CACHE_VERSION:
            existing = {"v": _CACHE_VERSION}
        if calendar is not None and isinstance(calendar, dict):
            existing["calendar"] = calendar
        if deals is not None:
            existing["deals"] = deals[:200]
        if deal_symbols is not None:
            existing["deal_symbols"] = sorted({str(s).upper() for s in deal_symbols if s})[:40]
        payload = json.dumps(existing, separators=(",", ":")).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
    except Exception as e:
        log.warning("could not persist trade history cache: %s", e)
