#!/usr/bin/env python3
"""Deploy Sep23-25 full desk lock ($100 partition + exit ops) to FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/main.py",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/lib/riskDeskDefaults.js",
    "frontend/lib/scannerRiskSync.js",
    "frontend/hooks/useDeskSession.js",
    "frontend/components/InstitutionalRiskDesk.js",
]

CMD = r"""
set -euo pipefail
# Force risk file to $100 before restart
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/var/lib/bilshenz/scanner-risk.json')
p.parent.mkdir(parents=True, exist_ok=True)
raw={}
if p.exists():
    try: raw=json.loads(p.read_text() or '{}')
    except: raw={}
raw.update({
  'partition_usd': 100.0,
  'short_pct': 50.0,
  'long1_pct': 40.0,
  'long2_pct': 40.0,
  'locked': True,
  'partition_usd_locked': True,
  'exec_halted': bool(raw.get('exec_halted', False)),
})
p.write_text(json.dumps(raw, indent=2))
print('RISK_FILE', raw)
PY
cd /opt/bilshenz/binance_trading_system/python
python3 test_frozen_strategy.py
systemctl restart bilshenz-binance-api
sleep 9
systemctl is-active bilshenz-binance-api
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json, inspect
from pathlib import Path
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('CONTRACT_OK', snap['ops'])
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('LIVE partition', s.get('partition_usd'), 'locked', s.get('risk_locked'), s.get('partition_usd_locked'))
print('mode', h.get('mode'), 'exec', s.get('can_execute'), 'strategy', s.get('strategy_id'))
assert float(s.get('partition_usd') or 0) == 100.0, s
assert s.get('partition_usd_locked') is True or s.get('risk_locked') is True
import binance_connector as bc
cool=inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
assert 'max_wait_s: float = 12.0' in cool
assert 'immediate flatten' not in cool
assert 'forced to 12s' in cool or 'ignoring max_wait_s' in cool
print('COOL_LOCK_OK')
# Reject $50 via API
import urllib.request
tok=Path('/etc/bilshenz.env').read_text()
token=''
for l in tok.splitlines():
  if l.startswith('BRIDGE_TOKEN='): token=l.split('=',1)[1].strip().strip('"').strip("'")
body=json.dumps({'partition_usd':50,'short_pct':50,'long1_pct':40,'long2_pct':40}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/risk', data=body, method='POST',
  headers={'Content-Type':'application/json','X-Bridge-Token':token})
with urllib.request.urlopen(req, timeout=12) as r:
  out=json.loads(r.read().decode())
print('POST50_RESULT', out)
assert float(out.get('partition_usd') or 0) == 100.0
assert out.get('partition_usd_locked') is True
risk=json.loads(Path('/var/lib/bilshenz/scanner-risk.json').read_text())
print('DISK', risk)
assert float(risk['partition_usd']) == 100.0
print('PARTITION_LOCK_OK')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel.replace("/", "\\")
        print("upload", rel)
        sftp.put(str(local), f"/opt/bilshenz/{rel}")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
