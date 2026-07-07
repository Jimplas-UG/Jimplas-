#!/usr/bin/env bash
# Run ON the VPS as root (paste in Remote SSH terminal):
#   curl -fsSL https://raw.githubusercontent.com/Jimplas-UG/Jimplas-/main/deploy/ubuntu/vps-one-shot-deploy.sh | bash
# Or after clone: bash /opt/bilshenz/deploy/ubuntu/vps-one-shot-deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bilshenz}"
REPO="${REPO:-https://github.com/Jimplas-UG/Jimplas-.git}"
BRANCH="${BRANCH:-main}"

echo "=== Bilshenz VPS deploy ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates ufw python3 python3-venv python3-pip

if ! command -v node &>/dev/null || [[ "$(node -v 2>/dev/null)" != v20* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

mkdir -p "$APP_DIR" /var/log/bilshenz
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --depth 1 -b "$BRANCH" "$REPO" "$APP_DIR"
else
  cd "$APP_DIR" && git fetch origin && git checkout "$BRANCH" && git pull --ff-only origin "$BRANCH"
fi

cd "$APP_DIR/backend"
npm ci 2>/dev/null || npm install

cd "$APP_DIR/binance_trading_system/python"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$APP_DIR/backend/validation/data"

if [[ ! -f /etc/bilshenz.env ]]; then
  cp "$APP_DIR/deploy/bilshenz.env.example" /etc/bilshenz.env
  # Safe defaults for first boot — edit keys before live trading
  sed -i 's/^BINANCE_TESTNET=.*/BINANCE_TESTNET=1/' /etc/bilshenz.env
  sed -i 's/^FORWARD_DRY_RUN=.*/FORWARD_DRY_RUN=1/' /etc/bilshenz.env
  sed -i 's/^SCANNER_EXEC=.*/SCANNER_EXEC=1/' /etc/bilshenz.env
  BRIDGE=$(openssl rand -hex 24 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')
  DESK=$(openssl rand -hex 16 2>/dev/null || echo "desk-$(date +%s)")
  sed -i "s/^BRIDGE_TOKEN=.*/BRIDGE_TOKEN=$BRIDGE/" /etc/bilshenz.env
  sed -i "s/^DESK_API_KEY=.*/DESK_API_KEY=$DESK/" /etc/bilshenz.env
  chmod 600 /etc/bilshenz.env
  echo ""
  echo "=== SAVE THESE (for frontend/.env.local on your PC) ==="
  grep -E '^(BRIDGE_TOKEN|DESK_API_KEY)=' /etc/bilshenz.env
  echo "=== EDIT /etc/bilshenz.env — add BINANCE_API_KEY and BINANCE_API_SECRET ==="
fi

npm run strategy:freeze --prefix "$APP_DIR/backend" 2>/dev/null || true

cp -f "$APP_DIR/deploy/systemd/"*.service /etc/systemd/system/
cp -f "$APP_DIR/deploy/logrotate/tradingbot" /etc/logrotate.d/bilshenz 2>/dev/null || true
chmod +x "$APP_DIR/deploy/ubuntu/"*.sh 2>/dev/null || true

systemctl daemon-reload
systemctl enable bilshenz-binance-api bilshenz-desk-api
systemctl restart bilshenz-binance-api bilshenz-desk-api

ufw allow OpenSSH
ufw allow 8766/tcp comment 'bilshenz-binance-api'
ufw allow 8791/tcp comment 'bilshenz-desk-api'
ufw --force enable || true

sleep 3
echo ""
echo "=== Health ==="
curl -s --max-time 10 http://127.0.0.1:8766/health | head -c 500 || echo "binance-api not up yet"
echo ""
curl -s --max-time 10 http://127.0.0.1:8791/health 2>/dev/null | head -c 300 || curl -s --max-time 10 http://127.0.0.1:8791/ping 2>/dev/null | head -c 300 || echo "desk-api check manually"
echo ""
systemctl status bilshenz-binance-api --no-pager -l | head -15
echo ""
echo "=== Done. Public URLs ==="
echo "  Binance: http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):8766/health"
echo "  Desk:    http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):8791/health"
