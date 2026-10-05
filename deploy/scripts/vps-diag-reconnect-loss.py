#!/usr/bin/env python3
"""Diagnose reconnect + live positions/exec after user loss complaint."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
OUT = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "_diag_reconnect_out.txt"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r"""
set +e
echo '=== services ==='
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
echo '=== env exec flags ==='
grep -E '^(SCANNER_EXEC|SCANNER_ENABLED|FORWARD_DRY_RUN|BINANCE_FORCE)' /etc/bilshenz.env
echo '=== health ==='
curl -sS -m 6 http://127.0.0.1:8766/health > /tmp/h.json
""" + PY + r""" - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
print('connected', h.get('connected'), 'testnet', h.get('testnet'), 'cool', h.get('rest_cool_s'))
print('balance', h.get('account_balance') or h.get('balance'))
print('partition', h.get('partition_usd'))
print('exec', h.get('execution_enabled'), 'block', h.get('block_reason') or h.get('exec_block'))
for name in ('tick_stream','scanner_stream','user_data_stream'):
    print(name, h.get(name))
# nested scanner/exec if present
for k in sorted(h.keys()):
    if k in ('tick_stream','scanner_stream','user_data_stream'):
        continue
    v=h[k]
    if isinstance(v, dict) and k in ('scanner','execution','account','risk','diagnostics','pair_isolation'):
        print(k, v)
PY
echo '=== diagnostics endpoint ==='
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 6 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/d.json
""" + PY + r""" - <<'PY'
import json
try:
  d=json.load(open('/tmp/d.json'))
except Exception as e:
  print('diag_parse', e); raise SystemExit
print('diag_ok', d.get('ok'), 'binance_ms', d.get('binance_latency_ms'), 'cpu', d.get('cpu_pct'))
print('mem', d.get('memory'))
print('user', d.get('user_data_stream'))
print('scanner_stream', d.get('scanner_stream'))
print('pair', d.get('pair_isolation'))
print('exec', d.get('execution'))
print('scanner', d.get('scanner'))
print('keys', sorted(d.keys())[:40])
PY
echo '=== open positions ==='
curl -sS -m 8 -H "Authorization: Bearer $TOK" "http://127.0.0.1:8766/api/positions" > /tmp/pos.json
""" + PY + r""" - <<'PY'
import json
try:
  p=json.load(open('/tmp/pos.json'))
except Exception as e:
  print('pos_err', e); print(open('/tmp/pos.json').read()[:500]); raise SystemExit
if isinstance(p, dict):
  rows=p.get('positions') or p.get('rows') or p.get('data') or p
  print('pos_keys', list(p.keys())[:20])
else:
  rows=p
if isinstance(rows, list):
  print('n', len(rows))
  for r in rows[:20]:
    if not isinstance(r, dict):
      print(r); continue
    print({k:r.get(k) for k in ('symbol','side','positionAmt','positionSide','entryPrice','unRealizedProfit','leverage','notional') if k in r or True})
else:
  print(type(rows), str(rows)[:500])
PY
echo '=== recent MOVR / margin / exec ==='
grep -iE 'insufficient|MOVR|EXEC_FAIL|LONG2|SMART_EXIT|user data stream' /var/log/bilshenz/binance-api.log | tail -50
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    OUT.write_text(out + ("\n---stderr---\n" + err if err.strip() else ""), encoding="utf-8")
    # ascii-safe console
    print(out.encode("ascii", "replace").decode("ascii"))
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    print("WROTE", OUT)
    c.close()


if __name__ == "__main__":
    main()
