#!/usr/bin/env python3
"""Close 1000RATSUSDT naked 10x short, set lever 5x, clear halt, re-arm exec."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
SYM = "1000RATSUSDT"

CMD = rf"""
set -e
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, time, urllib.request
from pathlib import Path

SYM = "{SYM}"
tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {{'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'}}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=H, method='POST'
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())

print('=== BEFORE ===')
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {{}}
print('halt', sc.get('user_exec_halted'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'kernel', sc.get('rule_kernel'))
pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
for p in items:
    print('POS', p.get('symbol'), p.get('positionSide'), p.get('volume'), 'lev', p.get('leverage') or p.get('exchange_leverage'))

rats = [p for p in items if str(p.get('symbol') or '').upper() == SYM]
if rats:
    print('=== CLOSE_PAIR', SYM, '===')
    try:
        r = post('http://127.0.0.1:8766/api/close', {{'symbol': SYM, 'close_pair': True, 'position_side': 'SHORT'}})
        print('CLOSE', json.dumps(r, default=str)[:900])
    except Exception as e:
        body = getattr(e, 'read', lambda: b'')()
        print('CLOSE_ERR', e, body[:500] if body else '')
        # fallback short leg
        try:
            r = post('http://127.0.0.1:8766/api/close', {{'symbol': SYM, 'position_side': 'SHORT'}})
            print('CLOSE_SHORT', json.dumps(r, default=str)[:900])
        except Exception as e2:
            body2 = getattr(e2, 'read', lambda: b'')()
            print('CLOSE_SHORT_ERR', e2, body2[:500] if body2 else '')
            raise
else:
    print('NO_RATS_POSITION — skip close')

# wait for flat
flat = False
for i in range(20):
    time.sleep(1)
    pos = get('http://127.0.0.1:8766/api/positions')
    items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
    rats = [p for p in items if str(p.get('symbol') or '').upper() == SYM]
    print(i, 'remaining', [(p.get('symbol'), p.get('positionSide'), p.get('volume')) for p in items])
    if not rats:
        flat = True
        break
if not flat:
    raise SystemExit('RATS_STILL_OPEN')

# Set leverage 5x via connector on VPS (process import not available); use signed REST through a tiny helper
print('=== SET_LEVERAGE_5X ===')
try:
    # Use running connector path via Python one-liner against env keys
    import os
    from binance_connector import BinanceConnector, BinanceConfig
    # Prefer live env from process — fall back to bilshenz.env
    env = {{}}
    for ln in Path('/etc/bilshenz.env').read_text().splitlines():
        if '=' in ln and not ln.strip().startswith('#'):
            k, v = ln.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    key = env.get('BINANCE_API_KEY') or env.get('BINANCE_KEY') or ''
    secret = env.get('BINANCE_API_SECRET') or env.get('BINANCE_SECRET') or ''
    testnet = str(env.get('BINANCE_TESTNET', '1')).lower() in ('1','true','yes','on')
    # If keys empty, skip — bridge owns session; try bridge health only
    if key and secret:
        bc = BinanceConnector(BinanceConfig(api_key=key, api_secret=secret, testnet=testnet, paper=False))
        bc.configure(key, secret, testnet)
        if hasattr(bc, 'ensure_exchange_leverage'):
            print('lev_ensure', bc.ensure_exchange_leverage(SYM, 5))
        elif hasattr(bc, 'set_leverage'):
            print('lev_set', bc.set_leverage(SYM, 5))
        else:
            print('no_lev_api', dir(bc)[:20])
    else:
        print('NO_ENV_KEYS — leverage will be set on next prepare; book is flat')
except Exception as e:
    print('LEV_WARN', type(e).__name__, e)

# Clear persisted halt
risk = Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw = json.loads(risk.read_text() or '{{}}')
    if not isinstance(raw, dict):
        raw = {{}}
    raw['exec_halted'] = False
    raw['partition_usd'] = 100.0
    risk.write_text(json.dumps(raw, indent=2) + '\n')
    print('CLEARED_RISK_HALT')

# Re-arm scanner exec
print('=== REARM ===')
r = post('http://127.0.0.1:8766/api/scanner/exec', {{'enabled': True}})
print('EXEC', r)

# Give watchdog a beat after flat
time.sleep(3)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {{}}
pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
print('=== AFTER ===')
print('can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'))
print('kernel', sc.get('rule_kernel'))
print('active', sc.get('active_symbol'), 'pos', len(items))
for p in items:
    print(' ', p.get('symbol'), p.get('positionSide'), p.get('volume'), 'lev', p.get('leverage'))

assert not items, items
assert sc.get('can_execute') is True, sc
assert not sc.get('user_exec_halted'), sc
assert (sc.get('rule_kernel') or {{}}).get('halt_codes') in ([], None), sc.get('rule_kernel')
print('RATS_FLAT_REARMED_OK')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=180)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
