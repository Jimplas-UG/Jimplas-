#!/usr/bin/env python3
"""Verify deployed close params on VPS (no live order)."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

REMOTE = r"""cd /opt/bilshenz/binance_trading_system/python && python3 <<'PY'
from binance_connector import BinanceConnector
from types import SimpleNamespace

c = BinanceConnector.__new__(BinanceConnector)
c.cfg = SimpleNamespace(paper=False)
c._hedge_mode = True
c.is_hedge_mode = lambda: True
p = c._market_close_params(
    symbol="TACUSDT",
    side="BUY",
    quantity=58644.0,
    client_order_id="verify",
    hedge_position_side="SHORT",
)
print("close_params", p)
assert "reduceOnly" not in p
assert p.get("positionSide") == "SHORT"
print("VERIFY_OK")
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(REMOTE, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err.strip():
        print(err, file=sys.stderr)
    client.close()
    return 0 if "VERIFY_OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
