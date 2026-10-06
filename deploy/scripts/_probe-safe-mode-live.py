#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS http://127.0.0.1:8766/health | /opt/bilshenz/binance_trading_system/python/.venv/bin/python -c "import sys,json; h=json.load(sys.stdin); sc=h.get('scanner') or {}; print('safe',sc.get('safe_mode'),'halt',sc.get('user_exec_halted'),'can',sc.get('can_execute'),'stuck',sc.get('stuck_close_symbols'),'over',sc.get('oversize_external_symbols'),'codes',sc.get('rule_halt_codes'),'reason',sc.get('safe_mode_reason'),'err',sc.get('last_exec_error'))"
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions | /opt/bilshenz/binance_trading_system/python/.venv/bin/python -c "import sys,json; d=json.load(sys.stdin); ps=[p for p in (d.get('positions') or []) if abs(float(p.get('volume') or p.get('positionAmt') or 0))>1e-12]; print('open',len(ps));
[print(p.get('symbol'),p.get('positionSide') or p.get('side'),p.get('volume') or p.get('positionAmt')) for p in ps]"
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-500:])
    c.close()

if __name__ == "__main__":
    main()
