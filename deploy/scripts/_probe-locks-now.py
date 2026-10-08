#!/usr/bin/env python3
"""Confirm October capital-lock markers are on the live FRA tree."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
/opt/bilshenz/binance_trading_system/python/.venv/bin/python - <<'PY'
from pathlib import Path
import inspect
import momentum_scanner as ms
import binance_connector as bc
msrc = inspect.getsource(ms.MomentumScanner._manage_positions)
ssrc = inspect.getsource(bc.BinanceConnector.close_by_position_side)
csrc = inspect.getsource(bc.BinanceConnector.close_position)
psrc = inspect.getsource(bc.BinanceConnector.positions)
print("naked_5x_not_10x", "target = LONG1_LEVERAGE" not in msrc and "symbol_exchange_leverage" in msrc)
print("hedge_episode", hasattr(ms.MomentumScanner, "_hedge_episode_active"))
print("solo_gate", hasattr(ms.MomentumScanner, "_solo_hedge_exit_allowed"))
print("manual_clamp", hasattr(ms.MomentumScanner, "clamp_manual_open_qty"))
print("side_close_chunks", "too_many_close_chunks" in ssrc)
print("short_abort_if_long_left", "long_residual_abort_short" in csrc)
print("positions_fail_closed", "fail-closed empty" in psrc)
print("no_rule_kernel", not Path("rule_kernel.py").exists())
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-600:])
    c.close()


if __name__ == "__main__":
    main()
