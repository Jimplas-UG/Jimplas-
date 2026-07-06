#!/bin/bash
# Bilshenz production install — Ubuntu 24.04 LTS (DigitalOcean 1 vCPU / 2 GB)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bilshenz}"
REPO="${REPO:-https://github.com/Jimplas-UG/Jimplas-.git}"
BRANCH="${BRANCH:-main}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates ufw python3 python3-venv python3-pip

# Node 20 LTS
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

mkdir -p "$APP_DIR" /var/log/bilshenz
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --depth 1 -b "$BRANCH" "$REPO" "$APP_DIR"
else
  cd "$APP_DIR" && git fetch origin && git checkout "$BRANCH" && git pull --ff-only
fi

cd "$APP_DIR/backend"
npm ci 2>/dev/null || npm install

cd "$APP_DIR/binance_trading_system/python"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$APP_DIR/backend/validation/data"

if [[ ! -f /etc/bilshenz.env ]]; then
  cp "$APP_DIR/.env.example" /etc/bilshenz.env
  chmod 600 /etc/bilshenz.env
  echo "EDIT /etc/bilshenz.env — set BINANCE_API_KEY, BINANCE_API_SECRET, BRIDGE_TOKEN, DESK_API_KEY"
fi

npm run strategy:freeze --prefix "$APP_DIR/backend" || true

cp -f "$APP_DIR/deploy/systemd/"*.service /etc/systemd/system/
cp -f "$APP_DIR/deploy/logrotate/tradingbot" /etc/logrotate.d/bilshenz 2>/dev/null || true
systemctl daemon-reload
systemctl enable bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || \
  systemctl enable bilshenz-binance-api bilshenz-desk-api

ufw allow OpenSSH
ufw allow 8766/tcp comment 'bilshenz-binance-api'
ufw allow 8791/tcp comment 'bilshenz-desk-api'
ufw --force enable || true

systemctl restart bilshenz-binance-api bilshenz-desk-api 2>/dev/null || true

echo "Install done. Edit /etc/bilshenz.env then: systemctl restart bilshenz-binance-api"
echo "Health: curl -s http://127.0.0.1:8766/health | head"
