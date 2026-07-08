#!/usr/bin/env python3
"""Deploy live-market fixes + verify trading E2E on VPS."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
export GIT_PAGER=cat PAGER=cat
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git --no-pager log -1 --oneline

ENVF=/etc/bilshenz.env
grep -q '^FORWARD_DRY_RUN=' "$ENVF" && sed -i 's/^FORWARD_DRY_RUN=.*/FORWARD_DRY_RUN=0/' "$ENVF" || echo 'FORWARD_DRY_RUN=0' >> "$ENVF"
grep -q '^SCANNER_EXEC=' "$ENVF" && sed -i 's/^SCANNER_EXEC=.*/SCANNER_EXEC=1/' "$ENVF" || echo 'SCANNER_EXEC=1' >> "$ENVF"

# Kill leftover Gradle JVMs that steal RAM from trading
pkill -f 'GradleDaemon' 2>/dev/null || true
pkill -f 'KotlinCompileDaemon' 2>/dev/null || true

systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api
sleep 6

# Forward bot: ensure env + service for XAU strategy (no strategy logic change)
if [[ ! -f /etc/tradingbot.env ]]; then
  cat > /etc/tradingbot.env <<EOF
STRATEGY_FREEZE=1
PRODUCTION_MODE=1
PRODUCTION_NO_EXPIRY=1
BROKER_MODE=binance
BINANCE_API_URL=http://127.0.0.1:8766
BINANCE_SYMBOL=XAUUSDT
FORWARD_DRY_RUN=0
FORWARD_POLL_SEC=45
RISK_PCT=0.005
DESK_API_KEY=$(grep '^DESK_API_KEY=' /etc/bilshenz.env | cut -d= -f2-)
BRIDGE_TOKEN=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
TRADINGBOT_LOG_DIR=/var/log/tradingbot
EOF
fi
# Point forward bot at Binance bridge, keep dry-run aligned with bilshenz.env
grep -q '^BINANCE_API_URL=' /etc/tradingbot.env && sed -i 's|^BINANCE_API_URL=.*|BINANCE_API_URL=http://127.0.0.1:8766|' /etc/tradingbot.env || echo 'BINANCE_API_URL=http://127.0.0.1:8766' >> /etc/tradingbot.env
grep -q '^BROKER_MODE=' /etc/tradingbot.env && sed -i 's/^BROKER_MODE=.*/BROKER_MODE=binance/' /etc/tradingbot.env || echo 'BROKER_MODE=binance' >> /etc/tradingbot.env
grep -q '^FORWARD_DRY_RUN=' /etc/tradingbot.env && sed -i 's/^FORWARD_DRY_RUN=.*/FORWARD_DRY_RUN=0/' /etc/tradingbot.env || echo 'FORWARD_DRY_RUN=0' >> /etc/tradingbot.env
# Keep DESK_API_KEY in sync for desk routes used by forward bot
DESK_KEY=$(grep '^DESK_API_KEY=' /etc/bilshenz.env | cut -d= -f2- || true)
if [[ -n "$DESK_KEY" ]]; then
  grep -q '^DESK_API_KEY=' /etc/tradingbot.env && sed -i "s|^DESK_API_KEY=.*|DESK_API_KEY=$DESK_KEY|" /etc/tradingbot.env || echo "DESK_API_KEY=$DESK_KEY" >> /etc/tradingbot.env
fi
mkdir -p /var/log/tradingbot
cd /opt/bilshenz/backend
# Refresh freeze fingerprints only (does not change entry/exit parameters)
cd /opt/bilshenz/backend
npm run strategy:freeze >/tmp/strategy-freeze.out 2>&1 || { echo FREEZE_FAIL; cat /tmp/strategy-freeze.out; }
# Ensure BRIDGE_TOKEN in tradingbot.env for forward bot bridge auth
BRIDGE=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- || true)
if [[ -n "$BRIDGE" ]]; then
  grep -q '^BRIDGE_TOKEN=' /etc/tradingbot.env && sed -i "s|^BRIDGE_TOKEN=.*|BRIDGE_TOKEN=$BRIDGE|" /etc/tradingbot.env || echo "BRIDGE_TOKEN=$BRIDGE" >> /etc/tradingbot.env
fi
if [[ -f /opt/bilshenz/deploy/systemd/bilshenz-forward-bot.service ]]; then
  cp -f /opt/bilshenz/deploy/systemd/bilshenz-forward-bot.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable bilshenz-forward-bot 2>/dev/null || true
  systemctl restart bilshenz-forward-bot || true
fi
sleep 8
systemctl is-active bilshenz-forward-bot || true
tail -n 15 /var/log/tradingbot/forward-bot.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 15
cd /opt/bilshenz


echo === services ===
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null || true

set -a; . /etc/bilshenz.env; set +a
python3 <<'PY'
import json, urllib.request, os, time

H={'Authorization':'Bearer '+os.environ.get('DESK_API_KEY','')}

def get(url, headers=None, timeout=25):
  req=urllib.request.Request(url, headers=headers or {})
  with urllib.request.urlopen(req, timeout=timeout) as r:
    return json.loads(r.read().decode())

# wait for scanner warm
time.sleep(8)
h=get('http://127.0.0.1:8766/health')
sc=h.get('scanner') or {}; ss=h.get('scanner_stream') or {}
print('HEALTH connected=',h.get('connected'),'scanner_ws=',ss.get('ws_connected'),'ticks=',ss.get('ticks_received'),'can_execute=',sc.get('can_execute'),'block=',sc.get('exec_block'))
s=get('http://127.0.0.1:8791/v1/binance/api/scanner/snapshot', H)
rows=s.get('rows') or []
print('MARKET_ROWS', len(rows))
for r in rows[:6]:
  print(' ', r.get('symbol'), 'gain', r.get('pctGain'), '3m', r.get('pct3m'), '24h', r.get('pct24h'), r.get('status'))
t=get('http://127.0.0.1:8791/v1/binance/api/tick/XAUUSDT', H)
print('XAU_TICK', t.get('bid'), t.get('ask'), t.get('source'))
st=get('http://127.0.0.1:8791/v1/binance/api/status', H)
print('STATUS connected=',st.get('connected'),'can_execute=',st.get('can_execute'),'bal=',(st.get('account') or {}).get('balance'))
pos=get('http://127.0.0.1:8791/v1/binance/api/positions', H)
print('POSITIONS', len(pos.get('positions') or pos if isinstance(pos,list) else pos.get('positions') or []))
PY

echo === forward log ===
tail -n 25 /var/log/tradingbot/forward-bot.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 25 || echo NO_FORWARD_LOG
free -h | head -2
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/bilshenz-e2e-trading.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-e2e-trading.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-e2e-trading.sh", timeout=240)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0 if "MARKET_ROWS" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
