#!/usr/bin/env bash
# Pull latest code and restart services (run on VPS after git push).
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
cd "$APP_DIR"
git fetch origin
git checkout main
git pull --ff-only origin main

cd "$APP_DIR/binance_trading_system/python"
.venv/bin/pip install -q -r requirements.txt

cd "$APP_DIR/backend"
npm ci 2>/dev/null || npm install

systemctl daemon-reload
systemctl restart bilshenz-binance-api bilshenz-desk-api

bash "$APP_DIR/deploy/ubuntu/healthcheck.sh"
echo "Update complete."
