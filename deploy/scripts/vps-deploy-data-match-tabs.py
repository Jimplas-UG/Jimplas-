#!/usr/bin/env python3
"""Deploy data-match + tab-speed fixes (no strategy files)."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE_PY}/.venv/bin/python"

FILES = [
    ("binance_trading_system/python/binance_connector.py", f"{REMOTE_PY}/binance_connector.py"),
    ("frontend/App.js", "/opt/bilshenz/frontend/App.js"),
    ("frontend/screens/TradeScreen.js", "/opt/bilshenz/frontend/screens/TradeScreen.js"),
    ("frontend/components/OpenPositionsPanel.js", "/opt/bilshenz/frontend/components/OpenPositionsPanel.js"),
    ("frontend/lib/liveFloatingPnl.js", "/opt/bilshenz/frontend/lib/liveFloatingPnl.js"),
]

CMD = rf"""
set -euo pipefail
{PY} -m py_compile {REMOTE_PY}/binance_connector.py
# Restart bridge only — picks up position field truth without wiping strategy.
systemctl restart bilshenz-binance-api
sleep 5
systemctl is-active bilshenz-binance-api
# wait session
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -sS -m 4 http://127.0.0.1:8766/health >/tmp/h.json || {{ sleep 1; continue; }}
  {PY} -c "import json;h=json.load(open('/tmp/h.json'));import sys;sys.exit(0 if h.get('connected') else 1)" && break
  sleep 1
done
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions >/tmp/p.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status >/tmp/s.json
{PY} <<'PY'
import json, time, hmac, hashlib, urllib.request, urllib.parse, os
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session
s=load_binance_session() or {{}}
key=(s.get('api_key') or os.environ.get('BINANCE_API_KEY','')).strip()
sec=(s.get('api_secret') or os.environ.get('BINANCE_API_SECRET','')).strip()
params={{'timestamp': int(time.time()*1000)}}
qs=urllib.parse.urlencode(params)
sig=hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
req=urllib.request.Request(f'https://fapi.binance.com/fapi/v2/positionRisk?{{qs}}&signature={{sig}}', headers={{'X-MBX-APIKEY': key}})
with urllib.request.urlopen(req, timeout=12) as r:
    risk=json.loads(r.read())
bin_pos=[p for p in risk if abs(float(p.get('positionAmt') or 0))>0]
bot=json.load(open('/tmp/p.json'))
st=json.load(open('/tmp/s.json'))
acct=(st.get('account') or {{}})
print('bot_n', len(bot.get('positions') or []), 'bin_n', len(bin_pos))
print('acct_profit', acct.get('profit'), 'balance', acct.get('balance'))
for bp in bin_pos:
    sym=bp.get('symbol')
    match=next((x for x in (bot.get('positions') or []) if x.get('symbol')==sym), None)
    print('BIN', sym, 'entry', bp.get('entryPrice'), 'mark', bp.get('markPrice'), 'pnl', bp.get('unRealizedProfit'), 'lev', bp.get('leverage'))
    if match:
        print('BOT', sym, 'entry', match.get('price_open'), 'mark', match.get('markPrice'), 'pnl', match.get('profit'), 'lev', match.get('leverage'), 'xlev', match.get('exchange_leverage'))
        be=float(bp.get('entryPrice') or 0); oe=float(match.get('price_open') or 0)
        bpnl=float(bp.get('unRealizedProfit') or 0); opnl=float(match.get('profit') or 0)
        print('entry_diff', abs(be-oe), 'pnl_diff', abs(bpnl-opnl), 'lev_match', str(match.get('leverage'))==str(int(float(bp.get('leverage') or 0))))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel, remote in FILES:
        print("upload", rel)
        sftp.put(str(ROOT / rel), remote)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
