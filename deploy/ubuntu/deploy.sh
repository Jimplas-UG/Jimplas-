#!/usr/bin/env bash
# Full deploy on Ubuntu 24.04 DigitalOcean droplet
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="${APP_DIR:-/opt/bilshenz}"

echo "=== Bilshenz deploy ==="
bash "$ROOT/deploy/install-production.sh"

echo "=== Python venv + Binance API ==="
cd "$APP_DIR/binance_trading_system/python"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p /var/log/bilshenz
cp -f "$ROOT/deploy/logrotate/tradingbot" /etc/logrotate.d/bilshenz 2>/dev/null || true

systemctl daemon-reload
systemctl enable bilshenz-binance-api bilshenz-desk-api
systemctl restart bilshenz-binance-api bilshenz-desk-api

bash "$ROOT/deploy/ubuntu/healthcheck.sh"
echo "Deploy complete."
