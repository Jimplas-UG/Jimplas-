"""
Temporary strategy mode switch — research exhaustion_v1 vs live short_first_v1.

Default remains short_first_v1 (frozen). Set SCANNER_STRATEGY_MODE=exhaustion_v1
only for research / paper; do not enable on live capital until backtests clear.
"""

from __future__ import annotations

import os
from typing import Any

LIVE_MODE = "short_first_v1"
RESEARCH_MODE = "exhaustion_v1"


def active_strategy_mode() -> str:
    raw = (os.environ.get("SCANNER_STRATEGY_MODE") or LIVE_MODE).strip().lower()
    if raw in ("exhaustion_v1", "exhaustion", "research"):
        return RESEARCH_MODE
    return LIVE_MODE


def strategy_mode_snapshot() -> dict[str, Any]:
    mode = active_strategy_mode()
    return {
        "strategy_mode": mode,
        "live_default": LIVE_MODE,
        "research_enabled": mode == RESEARCH_MODE,
        "note": (
            "exhaustion_v1 is temporary/research: exhaustion score, regime gates, "
            "no short trail, ATR invalidation, conditional hedges. Live execution "
            "still uses short_first_v1 unless this env flag is set AND wiring is enabled."
        ),
    }
