"""
Environment configuration — loads .env, validates required vars, detects profile.
Never hardcode secrets; all credentials come from environment / .env files.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ (does not override existing)."""
    p = path or ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def detect_environment() -> str:
    explicit = (os.environ.get("BILSHENZ_ENV") or os.environ.get("NODE_ENV") or "").strip().lower()
    if explicit in ("production", "prod"):
        return "production"
    if explicit in ("test", "testing"):
        return "testing"
    if explicit in ("development", "dev"):
        return "development"
    if _truthy(os.environ.get("BINANCE_PAPER")):
        return "testing"
    return "production" if os.environ.get("BINANCE_API_KEY") else "development"


@dataclass
class AppSettings:
    env: str
    host: str
    port: int
    bridge_token: str
    log_dir: Path
    paper: bool
    testnet: bool

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def validate_startup(*, require_keys: bool = False) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors: list[str] = []
    env = detect_environment()
    paper = _truthy(os.environ.get("BINANCE_PAPER", "0"))

    if env == "production" and not paper:
        if not os.environ.get("BINANCE_API_KEY", "").strip():
            errors.append("BINANCE_API_KEY is required in production (or set BINANCE_PAPER=1)")
        if not os.environ.get("BINANCE_API_SECRET", "").strip():
            errors.append("BINANCE_API_SECRET is required in production (or set BINANCE_PAPER=1)")

    if require_keys and os.environ.get("BRIDGE_TOKEN", "").strip() == "" and env == "production":
        errors.append("BRIDGE_TOKEN is strongly recommended in production")

    try:
        port = int(os.environ.get("PORT", "8766"))
        if port < 1 or port > 65535:
            errors.append(f"PORT invalid: {port}")
    except ValueError:
        errors.append("PORT must be an integer")

    return errors


def load_settings() -> AppSettings:
    # Local .env then system env file (VPS: /etc/bilshenz.env)
    load_dotenv(ROOT / ".env")
    sys_env = Path("/etc/bilshenz.env")
    if sys_env.is_file():
        load_dotenv(sys_env)

    env = detect_environment()
    log_dir = Path(os.environ.get("LOG_DIR", ROOT / "logs"))
    return AppSettings(
        env=env,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8766")),
        bridge_token=os.environ.get("BRIDGE_TOKEN", "").strip(),
        log_dir=log_dir,
        paper=_truthy(os.environ.get("BINANCE_PAPER", "0")),
        testnet=_truthy(os.environ.get("BINANCE_TESTNET", "1")),
    )


def ensure_valid_or_exit() -> AppSettings:
    settings = load_settings()
    errors = validate_startup()
    if errors:
        for e in errors:
            print(f"[config] ERROR: {e}", file=sys.stderr)
        if settings.is_production and not settings.paper:
            sys.exit(1)
    return settings
