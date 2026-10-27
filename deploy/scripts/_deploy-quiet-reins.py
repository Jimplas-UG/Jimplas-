#!/usr/bin/env python3
"""Stop the forward-demo bars stampede and redeploy Sep quiet REST reins. Does not flatten."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
UPLOAD = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/scanner_stream.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
    "binance_trading_system/python/test_sep23_capital_locks.py",
    "binance_trading_system/python/test_close_orders.py",
]
CMD = r"""
set -e
# Second strategy was stamping 40-symbol × 90d M30 bars through the bridge — kill it.
systemctl stop bilshenz-forward-bot || true
systemctl disable bilshenz-forward-bot || true
# Belt: if someone re-enables the unit, it must not trade or flood bars.
python3 - <<'PY'
from pathlib import Path
# Live scanner env must keep FORWARD_DRY_RUN=0 — only neuter symbol flood there.
# tradingbot.env (forward unit) stays dry-run so a re-enable cannot place orders.
patches = {
    Path('/etc/bilshenz.env'): {'FORWARD_DRY_RUN': '0', 'FORWARD_MAX_SYMBOLS': '0', 'FORWARD_SYMBOLS': ''},
    Path('/etc/tradingbot.env'): {'FORWARD_DRY_RUN': '1', 'FORWARD_MAX_SYMBOLS': '0', 'FORWARD_SYMBOLS': ''},
}
for path, want in patches.items():
    if not path.exists():
        continue
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    out=[]; seen=set()
    for ln in lines:
        if not ln.strip() or ln.strip().startswith('#') or '=' not in ln:
            out.append(ln); continue
        k = ln.split('=',1)[0].strip()
        if k in want:
            out.append(f'{k}={want[k]}'); seen.add(k); continue
        out.append(ln); seen.add(k)
    for k,v in want.items():
        if k not in seen:
            out.append(f'{k}={v}')
    path.write_text('\n'.join(out)+'\n', encoding='utf-8')
    print('env_patched', path, want)
PY
cd /opt/bilshenz/binance_trading_system/python
rm -rf __pycache__
.venv/bin/python test_permanent_leak_locks.py 2>&1 | tail -n 8
.venv/bin/python test_sep23_capital_locks.py 2>&1 | tail -n 3
.venv/bin/python test_close_orders.py 2>&1 | tail -n 3
systemctl restart bilshenz-binance-api
sleep 12
systemctl is-active bilshenz-binance-api
systemctl is-active bilshenz-forward-bot || true
systemctl is-enabled bilshenz-forward-bot || true
python3 - <<'PY'
import json, time, urllib.request
from pathlib import Path
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('can', sc.get('can_execute'), 'cool', h.get('rest_cool_s'), 'part', sc.get('partition_usd'), 'active', sc.get('active_symbol'), 'halt', sc.get('user_exec_halted'))
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization':'Bearer '+tok})
st=json.loads(urllib.request.urlopen(req, timeout=25).read())
acct=st.get('account') or {}
print('WALLET', acct.get('balance'), 'FREE', acct.get('margin_free'), 'UPNL', acct.get('profit'))
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req, timeout=25).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0))>1e-12]
print('OPEN_N', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide') or p.get('type'), 'qty', p.get('volume'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'))
src=open('binance_connector.py', encoding='utf-8').read()
ms=open('momentum_scanner.py', encoding='utf-8').read()
main=open('main.py', encoding='utf-8').read()
print('MARK host_weight', '_foreign_rest_host' in src and 'host=' in src)
print('MARK bars_pause', 'bars paused' in main)
print('MARK defer_throttle', '_defer_tp_log_mono' in ms)
print('MARK partition', 'PARTITION_LOSS' in ms and '_qty_for_room' in ms)
print('MARK forward_unit', Path('/etc/systemd/system/bilshenz-forward-bot.service').exists())
# sample cool for 70s window is too long; just report now
print('DEPLOY_OK')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in UPLOAD:
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel}")
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=240)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()

if __name__ == "__main__":
    main()
