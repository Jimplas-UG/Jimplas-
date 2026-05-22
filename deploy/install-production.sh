#!/bin/bash
# Bilshenz production install on Ubuntu 22.04+ (DigitalOcean)
# MT5 terminal MUST run on Windows — set MT5_API_URL to that host in .env
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bilshenz}"
REPO="${REPO:-https://github.com/Jimplas-UG/Jimplas-.git}"
BRANCH="${BRANCH:-main}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates ufw

# Node 20 LTS
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

mkdir -p "$APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --depth 1 -b "$BRANCH" "$REPO" "$APP_DIR"
else
  cd "$APP_DIR" && git fetch origin && git checkout "$BRANCH" && git pull --ff-only
fi

cd "$APP_DIR/backend"
npm ci 2>/dev/null || npm install

mkdir -p /var/log/bilshenz
mkdir -p "$APP_DIR/backend/validation/data"

if [[ ! -f /etc/bilshenz.env ]]; then
  cp "$APP_DIR/deploy/bilshenz.env.example" /etc/bilshenz.env
  chmod 600 /etc/bilshenz.env
  echo "EDIT /etc/bilshenz.env — set DESK_API_KEY and MT5_API_URL (Windows host)"
fi

npm run strategy:freeze || true

DEPLOY_SRC="/tmp/bilshenz-deploy"
if [[ -d "$DEPLOY_SRC" ]]; then
  mkdir -p "$APP_DIR/deploy"
  cp -f "$DEPLOY_SRC"/*.service /etc/systemd/system/ 2>/dev/null || true
  cp -f "$DEPLOY_SRC/watchdog.ts" "$APP_DIR/deploy/" 2>/dev/null || true
  cp -f "$DEPLOY_SRC/bilshenz.env.example" "$APP_DIR/deploy/" 2>/dev/null || true
fi
if [[ -d "$APP_DIR/deploy/systemd" ]]; then
  cp -f "$APP_DIR/deploy/systemd/"*.service /etc/systemd/system/
fi
systemctl daemon-reload
systemctl enable bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog

ufw allow OpenSSH
ufw allow 8791/tcp comment 'bilshenz-desk-api'
ufw --force enable || true

systemctl restart bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog

echo "Install done. Check: systemctl status bilshenz-desk-api"
