#!/usr/bin/env python3
"""Force LF APK build start + fix status connected + verify forward."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    # upload fixed main.py (status connected)
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    sftp = c.open_sftp()
    sftp.put(str(ROOT / "binance_trading_system/python/main.py"), "/opt/bilshenz/binance_trading_system/python/main.py")
    build = (ROOT / "deploy/ubuntu/build-apk-fra.sh").read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    with sftp.file("/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh", "wb") as f:
        f.write(build)
    sftp.close()

    cmd = r"""
set -e
python3 - <<'PY'
from pathlib import Path
p=Path('/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh')
b=p.read_bytes().replace(b'\r\n',b'\n').replace(b'\r',b'\n')
# strip UTF-8 BOM if present
if b.startswith(b'\xef\xbb\xbf'):
    b=b[3:]
p.write_bytes(b)
print('hex_line4', p.read_bytes().splitlines()[3].hex())
print('repr_line4', repr(p.read_bytes().splitlines()[3]))
PY
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
# smoke the set line
bash -c 'set -euo pipefail; echo pipefail_ok'

# restart bridge for status fix
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile /opt/bilshenz/binance_trading_system/python/main.py
systemctl restart bilshenz-binance-api
sleep 5

TOKEN=$(python3 -c "from pathlib import Path
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if l.startswith('BRIDGE_TOKEN='):
    print(l.split('=',1)[1].strip().strip(chr(34)).strip(chr(39))); break")
curl -sS -m 8 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json
curl -sS -m 8 http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
st=json.load(open('/tmp/st.json')); h=json.load(open('/tmp/h.json')); s=h.get('scanner') or {}
print('status_connected', st.get('connected'), 'mode', st.get('mode'), 'keys', sorted(st.keys())[:20])
print('health_connected', h.get('connected'), 'exec', s.get('can_execute'), 'active', s.get('active_symbol'))
PY

systemctl restart bilshenz-forward-bot
sleep 4
systemctl is-active bilshenz-forward-bot
tail -n 12 /var/log/tradingbot/forward-bot.log || true

pkill -f build-apk-fra.sh || true
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_PID=$!
sleep 8
ps -ef | grep -E 'build-apk-fra|gradlew|expo' | grep -v grep || echo still_starting
echo '--- nohup ---'
cat /var/log/bilshenz/apk-build-nohup.out || true
echo '--- apk log ---'
tail -n 30 /var/log/bilshenz/apk-build.log || true
"""
    _, o, e = c.exec_command(cmd, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
