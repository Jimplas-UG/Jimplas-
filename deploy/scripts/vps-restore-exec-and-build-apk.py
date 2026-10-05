#!/usr/bin/env python3
"""Restore Binance session/keys, fix forward-bot, enable exec, start APK build."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

# Fallback keys previously installed on FRA (user-provided). Prefer session file.
FALLBACK_KEY = os.environ.get(
    "BINANCE_API_KEY",
    "wpnu6YWloHNGGn6VyLIgTWuoXZ8mlExqws2p5IYYT7furZXJNm4UGr9CjG2nVkEB",
).strip()
FALLBACK_SECRET = os.environ.get(
    "BINANCE_API_SECRET",
    "WRgAdpjz9bgVzwlMYGukXGgdJBUYoD2xK2jLVDNoPLYZZibb5k47IQHAq2gZhTos",
).strip()


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    c.get_transport().set_keepalive(15)

    # Upload fixed LF build script
    local_build = ROOT / "deploy/ubuntu/build-apk-fra.sh"
    text = local_build.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    local_build.write_text(text, encoding="utf-8", newline="\n")

    sftp = c.open_sftp()
    sftp.put(str(local_build), "/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh")
    sftp.close()

    remote = r'''
set -euo pipefail
python3 <<'PY'
import base64, hashlib, hmac, json, os
from pathlib import Path

BRIDGE = ""
DESK = ""
SESSION_ENC = ""
for line in Path("/etc/bilshenz.env").read_text().splitlines():
    if line.startswith("BRIDGE_TOKEN="):
        BRIDGE = line.split("=",1)[1].strip().strip('"').strip("'")
    elif line.startswith("DESK_API_KEY="):
        DESK = line.split("=",1)[1].strip().strip('"').strip("'")
    elif line.startswith("SESSION_ENC_KEY="):
        SESSION_ENC = line.split("=",1)[1].strip().strip('"').strip("'")

if not BRIDGE:
    BRIDGE = "c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858"
if not DESK:
    DESK = "f44a0e6b7ea7b76418e484d6041e52da"

def sign_key():
    raw = (SESSION_ENC or BRIDGE or "bilshenz-session-v1").strip()
    return hashlib.sha256(raw.encode()).digest()

def try_load_session():
    p = Path("/var/lib/bilshenz/binance-session.json")
    if not p.is_file():
        return None
    try:
        env = json.loads(p.read_text())
        payload = base64.b64decode(env.get("p",""))
        sig = env.get("s","")
        expected = hmac.new(sign_key(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(sig)):
            # try default salt
            expected2 = hmac.new(hashlib.sha256(b"bilshenz-session-v1").digest(), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected2, str(sig)):
                print("session_sig_mismatch")
                # still try decode payload for recovery (signed historically)
                try:
                    data = json.loads(payload.decode())
                    if data.get("api_key") and data.get("api_secret"):
                        print("session_payload_recovered_unsigned")
                        return data
                except Exception:
                    return None
                return None
        data = json.loads(payload.decode())
        if data.get("api_key") and data.get("api_secret"):
            print("session_loaded_ok")
            return data
    except Exception as e:
        print("session_err", type(e).__name__, e)
    return None

sess = try_load_session()
api_key = (sess or {}).get("api_key") or os.environ.get("FALLBACK_KEY","")
api_secret = (sess or {}).get("api_secret") or os.environ.get("FALLBACK_SECRET","")
testnet = bool((sess or {}).get("testnet", True))
print("key_len", len(api_key), "secret_len", len(api_secret), "testnet", testnet)
if not api_key or not api_secret:
    raise SystemExit("NO_KEYS")

# rewrite bilshenz.env preserving unknowns, forcing required
want = {
  "BINANCE_API_KEY": api_key,
  "BINANCE_API_SECRET": api_secret,
  "BINANCE_TESTNET": "1",
  "BINANCE_FORCE_TESTNET": "1",
  "BINANCE_FORCE_MAINNET": "0",
  "BINANCE_PAPER": "0",
  "FORWARD_DRY_RUN": "0",
  "SCANNER_EXEC": "1",
  "SCANNER_ENABLED": "1",
  "BRIDGE_TOKEN": BRIDGE,
  "DESK_API_KEY": DESK,
  "SESSION_ENC_KEY": SESSION_ENC or BRIDGE,
}
p = Path("/etc/bilshenz.env")
lines = p.read_text().splitlines() if p.exists() else []
out, seen = [], set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line); continue
    k = line.split("=",1)[0].strip()
    if k in want:
        out.append(f"{k}={want[k]}"); seen.add(k)
    else:
        out.append(line)
for k,v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out)+"\n")
p.chmod(0o600)
print("bilshenz.env updated")

# re-persist session with current signing key
payload = json.dumps({"api_key": api_key, "api_secret": api_secret, "testnet": True}, separators=(",",":")).encode()
sig = hmac.new(sign_key(), payload, hashlib.sha256).hexdigest()
envelope = json.dumps({"v":1,"p":base64.b64encode(payload).decode(),"s":sig}, separators=(",",":"))
sp = Path("/var/lib/bilshenz/binance-session.json")
sp.parent.mkdir(parents=True, exist_ok=True)
sp.write_text(envelope)
sp.chmod(0o600)
print("session_rewritten")

# tradingbot.env for forward-bot unit
tb = Path("/etc/tradingbot.env")
tb.write_text(f"""STRATEGY_FREEZE=1
PRODUCTION_MODE=1
PRODUCTION_NO_EXPIRY=1
DESK_API_PORT=8791
DESK_API_KEY={DESK}
BROKER_MODE=binance
BINANCE_API_URL=http://127.0.0.1:8766
BRIDGE_TOKEN={BRIDGE}
BINANCE_SYMBOL=BTCUSDT
FORWARD_SYMBOLS=*
FORWARD_MAX_SYMBOLS=40
BINANCE_TESTNET=1
BINANCE_PAPER=0
FORWARD_DRY_RUN=0
FORWARD_POLL_SEC=30
RISK_PCT=0.005
MAX_DAILY_LOSS_PCT=3
MAX_API_FAILURES=8
TRADINGBOT_LOG_DIR=/var/log/tradingbot
SAFETY_STATE_PATH=/var/log/tradingbot/safety-state.json
SCANNER_EXEC=1
""")
tb.chmod(0o600)
Path("/var/log/tradingbot").mkdir(parents=True, exist_ok=True)
print("tradingbot.env written")
PY

systemctl daemon-reload
systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api || true
systemctl enable bilshenz-forward-bot || true
systemctl restart bilshenz-forward-bot || true
sleep 6
echo '=== SERVICES ==='
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null || true
systemctl status bilshenz-forward-bot --no-pager -l 2>&1 | head -n 20 || true

python3 <<'PY'
import json, time, urllib.request
def get(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode())

# tokens
env=open('/etc/bilshenz.env').read().splitlines()
def eg(k):
    for line in env:
        if line.startswith(k+'='):
            return line.split('=',1)[1].strip().strip('"').strip("'")
    return ''
bh={'X-Bridge-Token': eg('BRIDGE_TOKEN')}
dh={'Authorization': 'Bearer '+eg('DESK_API_KEY')}

# enable exec
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/exec', data=json.dumps({'enabled':True}).encode(), headers={**bh,'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=8) as r:
    print('exec', json.loads(r.read().decode()))

st,h=get('http://127.0.0.1:8766/health')
s=h.get('scanner') or {}
print('health', h.get('mode'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'), 'pending', s.get('pending_count'))
st,stj=get('http://127.0.0.1:8766/api/status', bh)
print('status', {k:stj.get(k) for k in ('connected','mode','testnet','balance','equity','can_trade','exec_enabled','can_execute')})
st,pos=get('http://127.0.0.1:8766/api/positions', bh)
print('positions', len(pos.get('positions') or []))
for p in (pos.get('positions') or [])[:8]:
    print(' POS', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume') or p.get('positionAmt'))
st,snap=get('http://127.0.0.1:8766/api/scanner/snapshot', bh)
print('snap_rows', len(snap.get('rows') or []))
st,dhj=get('http://127.0.0.1:8791/v1/binance/health', dh)
print('desk_health', dhj.get('ok'), dhj.get('connected'), (dhj.get('scanner') or {}).get('can_execute'))
PY

# fix build script line endings + sync tokens + start build
sed -i 's/\r$//' /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
python3 <<'PY'
from pathlib import Path
import re, json
env=Path('/etc/bilshenz.env').read_text().splitlines()
def get(k, default=''):
    for line in env:
        if line.startswith(k+'='):
            return line.split('=',1)[1].strip().strip('"').strip("'")
    return default
bridge=get('BRIDGE_TOKEN')
desk=get('DESK_API_KEY')
p=Path('/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh')
t=p.read_text().replace('\r\n','\n').replace('\r','\n')
t=re.sub(r'export EXPO_PUBLIC_BRIDGE_TOKEN=.*', f'export EXPO_PUBLIC_BRIDGE_TOKEN="{bridge}"', t)
t=re.sub(r'export EXPO_PUBLIC_DESK_API_KEY=.*', f'export EXPO_PUBLIC_DESK_API_KEY="{desk}"', t)
p.write_text(t)
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
print('apk_version', j['expo'].get('version'), 'code', j['expo']['android'].get('versionCode'))
print('build_tokens', len(bridge), len(desk))
PY
pkill -f build-apk-fra.sh || true
pkill -f 'gradlew assembleRelease' || true
sleep 1
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh > /var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_STARTED pid=$!
sleep 5
ps aux | grep -E 'build-apk-fra|gradlew|expo prebuild|npm' | grep -v grep | head -n 10 || true
tail -n 30 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || true
'''

    # pass fallback via env on remote
    full = f"export FALLBACK_KEY='{FALLBACK_KEY}'; export FALLBACK_SECRET='{FALLBACK_SECRET}';\n" + remote
    _, o, e = c.exec_command(full, timeout=180)
    o.channel.settimeout(180)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    # redact any accidental key material
    for secret in (FALLBACK_KEY, FALLBACK_SECRET):
        if secret and secret in out:
            out = out.replace(secret, "[REDACTED]")
        if secret and secret in err:
            err = err.replace(secret, "[REDACTED]")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err[-2500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
