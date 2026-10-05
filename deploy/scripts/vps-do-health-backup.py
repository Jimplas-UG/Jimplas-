#!/usr/bin/env python3
"""Read-only DO health check + backup of bilshenz critical state (no destroys)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP_DIR = f"/root/bilshenz-backups/{STAMP}"

CMD = rf"""
set -e
echo === HOST ===
hostname; uname -a; uptime; df -h / | tail -1; free -h | head -2
echo === SERVICES ===
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || true
systemctl is-active bilshenz-apk-server 2>/dev/null || echo apk-server:inactive
echo === GIT ===
cd /opt/bilshenz && git --no-pager log -1 --oneline && git status -sb | head -5
echo === HEALTH ===
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS --max-time 8 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('scanner') or {{}}; print('connected',d.get('connected'),'mode',d.get('mode'),'exec',s.get('can_execute'),'block',s.get('exec_block'),'active',s.get('active_symbol'))"
curl -sS --max-time 8 http://127.0.0.1:8791/health || true
echo
echo === BACKUP ===
mkdir -p {BACKUP_DIR}
# Env names only listed; full env copied with restricted perms (local root backup)
cp -a /etc/bilshenz.env {BACKUP_DIR}/bilshenz.env 2>/dev/null || true
cp -a /etc/tradingbot.env {BACKUP_DIR}/tradingbot.env 2>/dev/null || true
mkdir -p {BACKUP_DIR}/var-lib-bilshenz {BACKUP_DIR}/auth-data
cp -a /var/lib/bilshenz/. {BACKUP_DIR}/var-lib-bilshenz/ 2>/dev/null || true
cp -a /opt/bilshenz/backend/auth/data/. {BACKUP_DIR}/auth-data/ 2>/dev/null || true
# Never echo secret values — list keys only
echo ENV_KEYS_bilshenz:
grep -E '^[A-Z0-9_]+=' /etc/bilshenz.env 2>/dev/null | cut -d= -f1 | sort
echo ENV_KEYS_tradingbot:
grep -E '^[A-Z0-9_]+=' /etc/tradingbot.env 2>/dev/null | cut -d= -f1 | sort
echo BACKUP_PATH {BACKUP_DIR}
du -sh {BACKUP_DIR}
ls -la {BACKUP_DIR}
chmod -R go-rwx {BACKUP_DIR}
echo === POSITIONS_SUMMARY ===
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions | python3 -c "import sys,json; d=json.load(sys.stdin); ps=[p for p in (d.get('positions') or []) if abs(float(p.get('volume') or 0))>0]; print('open',len(ps));
[print(p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume'), p.get('price_open')) for p in ps[:20]]"
echo === UFW ===
ufw status 2>/dev/null | head -20 || true
echo DONE_OK
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
