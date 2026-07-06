"""
Production logging — rotating files under logs/ (or LOG_DIR).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    lvl = getattr(logging, level.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(lvl)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    files = {
        "app.log": logging.INFO,
        "errors.log": logging.ERROR,
        "trades.log": logging.INFO,
        "websocket.log": logging.INFO,
    }
    for name, file_lvl in files.items():
        h = RotatingFileHandler(
            log_dir / name,
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        h.setLevel(file_lvl)
        h.setFormatter(fmt)
        root.addHandler(h)

    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    trade_log = logging.getLogger("trades")
    trade_log.propagate = True
