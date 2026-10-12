#!/usr/bin/env python3
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
REMOTE = r"""
import json, urllib.request
from pathlib import Path
tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}
h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
st = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8766/api/status", headers=H), timeout=15).read())
sc = h.get("scanner") or {}
acct = st.get("account") or {}
src = Path("/opt/bilshenz/binance_trading_system/python/momentum_scanner.py").read_text(encoding="utf-8")
print("mode", h.get("mode"), "testnet", h.get("testnet"), st.get("testnet"), st.get("mode"))
print(
    "bal", acct.get("balance"), "profit", acct.get("profit"),
    "part", sc.get("partition_usd"), "can", sc.get("can_execute"), "halt", sc.get("user_exec_halted"),
)
print("gate", "_hedged_short_exit_net_ok" in src)
print("manage_defer", "_hedged_short_exit_net_ok" in src and "defer" in src)
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=25)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_probe-hedged-tp-live.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command(
        "/opt/bilshenz/binance_trading_system/python/.venv/bin/python /tmp/_probe-hedged-tp-live.py",
        timeout=30,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[:800])
    c.close()


if __name__ == "__main__":
    main()
