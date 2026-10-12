#!/usr/bin/env python3
"""Print live strategy knobs as the bridge env sees them."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python && set -a && . /etc/bilshenz.env && set +a
unset REST_BAN_FILE
.venv/bin/python - <<'PY' 2>&1 | tail -n 3
import momentum_scanner as m, frozen_strategy as f
print("retrace", m.RETRACE_ENTRY_PCT, "gain", m.GAIN_THRESHOLD_PCT, "pair_time_h", m.HEDGED_MAX_HOLD_MS / 3600000,
      "inv", m.PAIR_INVALIDATION_PCT, "variant", f.STRATEGY_VARIANT)
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, _ = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    c.close()


if __name__ == "__main__":
    main()
