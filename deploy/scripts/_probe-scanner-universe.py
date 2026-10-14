#!/usr/bin/env python3
"""Why scanner market view is thin: coins tracked, stream state, recent logs."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
print('HEALTH_SCANNER', json.dumps(h.get('scanner') or {}, indent=2)[:1200])
print('STREAM', json.dumps(h.get('scanner_stream') or h.get('stream') or {}, indent=2)[:800])
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/snapshot', headers={'X-Bridge-Token': tok})
d=json.loads(urllib.request.urlopen(req, timeout=12).read())
print('SCANNER_META', json.dumps(d.get('scanner') or {}, indent=2)[:1500])
print('ROWS', len(d.get('rows') or []))
PY
echo '--- env knobs'
grep -E 'SCANNER_|FORWARD_|MAX_WATCH|MAX_SYMBOL' /etc/bilshenz.env | sed -E 's/(KEY|SECRET|TOKEN)=.*/\1=***/'
echo '--- recent scanner/stream log'
grep -hE 'symbol universe|scanner REST|scanner stream|load_symbols|symbols_tracked|liquidity skip|refreshed market|miniTicker|WATCHLIST|universe' /var/log/bilshenz/*.log 2>/dev/null | tail -n 40
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
