#!/usr/bin/env python3
"""Install Binance API credentials into /etc/bilshenz.env and restart bridge."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "161.35.112.53")
KEY_PATH = Path.home() / ".ssh" / "id_ed25519"
API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()


def main() -> int:
    if not API_KEY or not API_SECRET:
        print("BINANCE_API_KEY and BINANCE_API_SECRET required", file=sys.stderr)
        return 1

    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY_PATH))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    # Escape for single-quoted remote shell values
    k = API_KEY.replace("'", "'\"'\"'")
    s = API_SECRET.replace("'", "'\"'\"'")

    cmd = f"""
set -euo pipefail
ENVF=/etc/bilshenz.env
test -f "$ENVF"
if grep -q '^BINANCE_API_KEY=' "$ENVF"; then
  sed -i 's|^BINANCE_API_KEY=.*|BINANCE_API_KEY={k}|' "$ENVF"
else
  echo 'BINANCE_API_KEY={k}' >> "$ENVF"
fi
if grep -q '^BINANCE_API_SECRET=' "$ENVF"; then
  sed -i 's|^BINANCE_API_SECRET=.*|BINANCE_API_SECRET={s}|' "$ENVF"
else
  echo 'BINANCE_API_SECRET={s}' >> "$ENVF"
fi
for kv in 'BINANCE_TESTNET=0' 'BINANCE_PAPER=0' 'FORWARD_DRY_RUN=0' 'SCANNER_EXEC=1'; do
  key="${{kv%%=*}}"; val="${{kv#*=}}"
  if grep -q "^${{key}}=" "$ENVF"; then sed -i "s|^${{key}}=.*|${{key}}=${{val}}|" "$ENVF"
  else echo "${{key}}=${{val}}" >> "$ENVF"; fi
done
chmod 600 "$ENVF"
# Confirm lengths only — never print secrets
python3 - <<'PY'
from pathlib import Path
d={{}}
for line in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        a,b=line.split('=',1); d[a]=b.strip()
print('key_len', len(d.get('BINANCE_API_KEY','')))
print('secret_len', len(d.get('BINANCE_API_SECRET','')))
print('testnet', d.get('BINANCE_TESTNET'))
print('dry_run', d.get('FORWARD_DRY_RUN'))
print('scanner_exec', d.get('SCANNER_EXEC'))
PY
systemctl restart bilshenz-binance-api
sleep 8
systemctl is-active bilshenz-binance-api
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health
echo
"""
    _, o, e = c.exec_command(cmd, timeout=120)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    if err.strip():
        sys.stderr.buffer.write(("STDERR:\n" + err[-3000:] + "\n").encode("utf-8", errors="replace"))
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
