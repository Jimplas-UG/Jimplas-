#!/usr/bin/env python3
"""Ensure FRA APIs + forward bot executing, then start APK build."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"

# Keep bridge auth ON for new APK (tokens baked into EXPO_PUBLIC_*).
ENSURE_ENV = {
    "BINANCE_TESTNET": "1",
    "BINANCE_FORCE_TESTNET": "1",
    "BINANCE_FORCE_MAINNET": "0",
    "BINANCE_PAPER": "0",
    "FORWARD_DRY_RUN": "0",
    "SCANNER_EXEC": "1",
    "SCANNER_ENABLED": "1",
}

FRONTEND_SYNC = [
    "frontend/lib/wsReconnect.js",
    "frontend/broker/binanceTickStream.js",
    "frontend/broker/binanceScannerApi.js",
    "frontend/hooks/useTickScanner.js",
    "frontend/App.js",
    "frontend/lib/envConfig.js",
    "frontend/app.json",
    "frontend/app.config.js",
    "frontend/eas.json",
]

PY_SYNC = [
    "scanner_stream.py",
    "tick_stream.py",
    "user_data_stream.py",
    "binance_connector.py",
    "main.py",
    "position_manager.py",
]


def ssh() -> paramiko.SSHClient:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    c.get_transport().set_keepalive(15)
    return c


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 90) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    o.channel.settimeout(timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        out += "\n[stderr]\n" + err[-2500:]
    return out


def main() -> int:
    c = ssh()
    sftp = c.open_sftp()

    print("=== upload python ===")
    for name in PY_SYNC:
        local = ROOT / "binance_trading_system" / "python" / name
        if local.exists():
            print(f"  {name}")
            sftp.put(str(local), f"{REMOTE_PY}/{name}")

    print("=== upload frontend ===")
    for rel in FRONTEND_SYNC:
        local = ROOT / rel
        if local.exists():
            print(f"  {rel}")
            sftp.put(str(local), f"/opt/bilshenz/{rel}")

    sftp.put(str(ROOT / "deploy/ubuntu/build-apk-fra.sh"), "/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh")
    sftp.close()

    # write remote helpers via sftp instead of nested f-strings
    helper = ROOT / "deploy" / "scripts" / "_remote_ensure_exec.py"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import json\n"
        f"want = {repr(ENSURE_ENV)}\n"
        "p = Path('/etc/bilshenz.env')\n"
        "lines = p.read_text().splitlines()\n"
        "out, seen = [], set()\n"
        "for line in lines:\n"
        "    if not line or line.lstrip().startswith('#') or '=' not in line:\n"
        "        out.append(line); continue\n"
        "    k = line.split('=', 1)[0].strip()\n"
        "    if k in want:\n"
        "        out.append(f'{k}={want[k]}'); seen.add(k)\n"
        "    else:\n"
        "        out.append(line)\n"
        "for k, v in want.items():\n"
        "    if k not in seen:\n"
        "        out.append(f'{k}={v}')\n"
        "DEFAULT_TOKEN = 'c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858'\n"
        "fixed = False\n"
        "for i, l in enumerate(out):\n"
        "    if l.startswith('BRIDGE_TOKEN='):\n"
        "        val = l.split('=',1)[1].strip().strip('\"').strip(\"'\")\n"
        "        if len(val) < 8:\n"
        "            out[i] = 'BRIDGE_TOKEN=' + DEFAULT_TOKEN\n"
        "        fixed = True\n"
        "        break\n"
        "if not fixed:\n"
        "    out.append('BRIDGE_TOKEN=' + DEFAULT_TOKEN)\n"
        "p.write_text('\\n'.join(out) + '\\n')\n"
        "print('env_updated', want)\n"
        "pj = Path('/opt/bilshenz/frontend/app.json')\n"
        "j = json.loads(pj.read_text())\n"
        "expo = j.setdefault('expo', {})\n"
        "android = expo.setdefault('android', {})\n"
        "vc = int(android.get('versionCode') or 14) + 1\n"
        "vn = str(expo.get('version') or '1.4.3')\n"
        "parts = vn.split('.')\n"
        "try:\n"
        "    parts[-1] = str(int(parts[-1]) + 1)\n"
        "except Exception:\n"
        "    parts = ['1', '4', '4']\n"
        "vn = '.'.join(parts)\n"
        "expo['version'] = vn\n"
        "android['versionCode'] = vc\n"
        "pj.write_text(json.dumps(j, indent=2) + '\\n')\n"
        "print(f'version={vn} versionCode={vc}')\n"
    )
    sftp2 = c.open_sftp()
    sftp2.put(str(helper), "/tmp/_remote_ensure_exec.py")
    sftp2.close()

    phase1 = f"""
set -euo pipefail
python3 /tmp/_remote_ensure_exec.py
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile \\
  {REMOTE_PY}/main.py {REMOTE_PY}/binance_connector.py {REMOTE_PY}/scanner_stream.py \\
  {REMOTE_PY}/tick_stream.py {REMOTE_PY}/user_data_stream.py {REMOTE_PY}/position_manager.py
systemctl restart bilshenz-binance-api || true
systemctl restart bilshenz-desk-api || true
systemctl restart bilshenz-forward-bot || true
sleep 5
echo '=== SERVICES ==='
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null || true
"""
    print(run(c, phase1, timeout=120))

    phase2 = r"""
set +e
echo '=== API SMOKE ==='
python3 <<'PY'
import json, time, urllib.request, urllib.error

def get(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', 'replace')
            ms = (time.perf_counter() - t0) * 1000
            return r.status, body, ms, None
    except Exception as e:
        return 0, '', (time.perf_counter() - t0) * 1000, e

# tokens
env = open('/etc/bilshenz.env').read().splitlines()
def envget(k):
    for line in env:
        if line.startswith(k+'='):
            return line.split('=',1)[1].strip().strip('"').strip("'")
    return ''
bridge = envget('BRIDGE_TOKEN')
desk = envget('DESK_API_KEY')
print('token_bridge', len(bridge), 'desk', len(desk))

checks = []
# bridge health (public)
st, body, ms, err = get('http://127.0.0.1:8766/health')
checks.append(('bridge/health', st, ms, err, body[:200] if body else ''))
# bridge APIs
bh = {'X-Bridge-Token': bridge} if bridge else {}
for path in ['/api/status', '/api/positions', '/api/scanner/snapshot', '/api/scanner/exec']:
    if path.endswith('/exec'):
        req = urllib.request.Request(
            'http://127.0.0.1:8766'+path,
            data=b'{}',
            headers={**bh, 'Content-Type': 'application/json'},
            method='POST',
        )
        t0=time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                body=r.read().decode(); ms=(time.perf_counter()-t0)*1000
                checks.append((path, r.status, ms, None, body[:160]))
        except Exception as e:
            checks.append((path, 0, (time.perf_counter()-t0)*1000, e, ''))
    else:
        st, body, ms, err = get('http://127.0.0.1:8766'+path, bh)
        checks.append((path, st, ms, err, body[:160] if body else ''))

# desk proxy
dh = {'Authorization': f'Bearer {desk}'} if desk else {}
st, body, ms, err = get('http://127.0.0.1:8791/v1/binance/health', dh)
checks.append(('desk/health', st, ms, err, body[:160] if body else ''))
st, body, ms, err = get('http://127.0.0.1:8791/v1/binance/api/scanner/snapshot', dh)
checks.append(('desk/snapshot', st, ms, err, body[:120] if body else ''))

for name, st, ms, err, snip in checks:
    ok = st and 200 <= st < 400 and not err
    print(f"{'OK' if ok else 'FAIL'} {name} http={st} ms={ms:.0f} err={err} snip={snip[:80]!r}")

# force exec enable if halted
try:
    req = urllib.request.Request(
        'http://127.0.0.1:8766/api/scanner/exec',
        data=json.dumps({'enabled': True}).encode(),
        headers={**bh, 'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        d=json.loads(r.read().decode())
        print('exec_enable', {k:d.get(k) for k in ('ok','exec_enabled','can_execute','exec_block','user_exec_halted')})
except Exception as e:
    print('exec_enable_err', e)

# health summary
st, body, ms, err = get('http://127.0.0.1:8766/health')
h=json.loads(body) if body else {}
s=h.get('scanner') or {}
print('SUMMARY mode', h.get('mode'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('SUMMARY exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'),
      'pending', s.get('pending_count'), 'strategies', s.get('active_strategies'))
print('SUMMARY last_err', s.get('last_exec_error'))
for e in (s.get('execution_events') or [])[-6:]:
    print('EVT', e.get('symbol'), e.get('stage'), e.get('leg'), e.get('fill_price') or e.get('error'))
PY

echo '=== POSITIONS ==='
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions | python3 -c 'import sys,json;d=json.load(sys.stdin);pos=d.get("positions") or [];print("n",len(pos));
[print("POS",p.get("symbol"),p.get("positionSide") or p.get("type"),p.get("volume") or p.get("positionAmt"),"pnl",p.get("unRealizedProfit") or p.get("profit")) for p in pos[:12]]'

echo '=== FORWARD LOG ==='
systemctl status bilshenz-forward-bot --no-pager -l 2>&1 | head -n 25 || true
tail -n 30 /var/log/bilshenz/forward-bot.log 2>/dev/null || tail -n 30 /var/log/tradingbot/forward-bot.log 2>/dev/null || echo no_forward_log
journalctl -u bilshenz-forward-bot -n 20 --no-pager 2>&1 | tail -n 20 || true

echo '=== BRIDGE LOG EXEC ==='
grep -E 'filled|submit|SHORT|Long 1|exec|can_execute|418|cool' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 35 || true
"""
    print(run(c, phase2, timeout=90))

    # Start APK build (do NOT clear BRIDGE_TOKEN)
    phase3 = r"""
set -euo pipefail
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
sed -i 's/\r$//' /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
# sync BRIDGE_TOKEN into build script from env
python3 - <<'PY'
from pathlib import Path
import re
env = Path('/etc/bilshenz.env').read_text().splitlines()
def get(k):
    for line in env:
        if line.startswith(k+'='):
            return line.split('=',1)[1].strip().strip('"').strip("'")
    return ''
bridge = get('BRIDGE_TOKEN') or 'c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858'
desk = get('DESK_API_KEY') or 'f44a0e6b7ea7b76418e484d6041e52da'
p = Path('/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh')
t = p.read_text()
t = re.sub(r'export EXPO_PUBLIC_BRIDGE_TOKEN=.*', f'export EXPO_PUBLIC_BRIDGE_TOKEN="{bridge}"', t)
t = re.sub(r'export EXPO_PUBLIC_DESK_API_KEY=.*', f'export EXPO_PUBLIC_DESK_API_KEY="{desk}"', t)
p.write_text(t)
print('build_tokens_synced', len(bridge), len(desk))
# show version
import json
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
print('apk_version', j['expo'].get('version'), 'code', j['expo'].get('android',{}).get('versionCode'))
PY
pkill -f build-apk-fra.sh || true
pkill -f 'gradlew assembleRelease' || true
sleep 1
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh > /var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_PID=$!
sleep 4
ps aux | grep -E 'build-apk-fra|gradlew|expo prebuild' | grep -v grep | head -n 8 || true
tail -n 25 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
tail -n 15 /var/log/bilshenz/apk-build.log 2>/dev/null || true
"""
    print(run(c, phase3, timeout=60))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
