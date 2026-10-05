#!/usr/bin/env python3
"""Check user WS after fix + try private URL variants with live listenKey from bridge memory."""
from __future__ import annotations

from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r"""
set -e
echo '=== key env lengths (no values) ==='
python3 - <<'PY'
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    v=v.strip().strip('"').strip("'")
    if 'KEY' in k or 'SECRET' in k or 'TOKEN' in k:
        print(f'{k} len={len(v)} empty={not bool(v)}')
PY
echo '=== health ==='
sleep 2
curl -sS -m 5 http://127.0.0.1:8766/health > /tmp/h.json
""" + PY + r""" - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
print('connected', h.get('connected'), 'testnet', h.get('testnet'))
for name in ('tick_stream','scanner_stream','user_data_stream'):
    print(name, h.get(name))
PY
echo '=== journal user/scanner ==='
journalctl -u bilshenz-binance-api --since '2 minutes ago' --no-pager | grep -iE 'user data|listenKey|private|HTTP|scanner WS|tick stream|connecting' | tail -50
"""

# Inject a one-shot probe into the running app by hitting an admin endpoint if any;
# else create listenKey using session keys via a small FastAPI call.
# Use gunicorn? No — call Python that imports session decrypt.

PROBE2 = r'''
import asyncio, json, time, os, sys
sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
os.chdir("/opt/bilshenz/binance_trading_system/python")

# Reuse app session restore to get connector keys
from binance_connector import BinanceConnector
# Try load from encrypted session used by main
import glob
cands=glob.glob("/opt/bilshenz/**/*session*", recursive=True)+glob.glob("/var/lib/bilshenz/**", recursive=True)
print("cands", [c for c in cands if "node_modules" not in c and "kotlin" not in c][:30])

# Ask running process via unix? Use REST login state — /account
import urllib.request
tok=None
for line in open("/etc/bilshenz.env"):
    if line.startswith("BRIDGE_TOKEN="):
        tok=line.split("=",1)[1].strip().strip('"').strip("'")
        break
headers={"Authorization": f"Bearer {tok}"} if tok else {}
for path in ["/account","/v1/account","/status","/positions"]:
    try:
        req=urllib.request.Request("http://127.0.0.1:8766"+path, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            body=r.read()[:300]
            print(path, r.status, body[:200])
    except Exception as e:
        print(path, type(e).__name__, str(e)[:120])
'''


def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("---stderr---", err[-2000:])
    _, o2, e2 = c.exec_command(f"{PY} -", timeout=40)
    o2.channel.sendall(PROBE2.encode())
    o2.channel.shutdown_write()
    print(o2.read().decode("utf-8", "replace"))
    print(e2.read().decode("utf-8", "replace")[-1500:])
    c.close()

if __name__ == "__main__":
    main()
