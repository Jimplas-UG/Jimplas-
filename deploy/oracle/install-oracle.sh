#!/usr/bin/env bash
# Install Bilshenz on an Oracle Cloud Ubuntu 24.04 instance from a bundle tarball.
# Installs and tests only: it does not start the bot, and trading stays off.
#
#   sudo bash install-oracle.sh /home/ubuntu/bilshenz-oracle-XXXX.tar.gz
set -euo pipefail

BUNDLE="${1:-}"
APP_DIR="/opt/bilshenz"
ENV_FILE="/etc/bilshenz.env"
STATE_DIR="/var/lib/bilshenz"
LOG_DIR="/var/log/bilshenz"

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
[[ -f "$BUNDLE" ]] || { echo "Usage: sudo bash install-oracle.sh <bundle.tar.gz>"; exit 1; }
if systemctl is-active --quiet bilshenz-binance-api 2>/dev/null; then
  echo "bilshenz-binance-api is running. Stop it first: sudo systemctl stop bilshenz-binance-api bilshenz-desk-api"
  exit 1
fi

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 python3-venv python3-pip \
  iptables-persistent netfilter-persistent logrotate chrony
if ! command -v node >/dev/null || [[ "$(node -v)" != v20* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Code"
mkdir -p "$APP_DIR" "$STATE_DIR" "$LOG_DIR"
chmod 700 "$STATE_DIR"
tar -xzf "$BUNDLE" -C "$APP_DIR"
find "$APP_DIR/deploy" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.template' \) \
  -exec sed -i 's/\r$//' {} +

echo "==> Python"
cd "$APP_DIR/binance_trading_system/python"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt pytest

echo "==> Node"
cd "$APP_DIR/backend"
npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

echo "==> Environment"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 600 "$APP_DIR/deploy/oracle/bilshenz.env.template" "$ENV_FILE"
  echo "Created $ENV_FILE from the template. Fill it in, or copy the old server's file."
fi
chmod 600 "$ENV_FILE"
sed -i 's/\r$//' "$ENV_FILE"

echo "==> Firewall"
# Oracle's Ubuntu image ships iptables rules ending in REJECT. Add ACCEPT above that rule and
# leave ufw alone. The VCN security list must open the same ports.
for port in 8766 8791; do
  if ! iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
netfilter-persistent save >/dev/null

echo "==> Log retention"
# 14 days is why the September logs no longer exist.
cat > /etc/logrotate.d/bilshenz <<'ROTATE'
/var/log/bilshenz/*.log {
  daily
  rotate 180
  compress
  delaycompress
  missingok
  notifempty
  copytruncate
}
ROTATE

echo "==> systemd"
cp -f "$APP_DIR/deploy/systemd/bilshenz-binance-api.service" /etc/systemd/system/
cp -f "$APP_DIR/deploy/systemd/bilshenz-desk-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bilshenz-binance-api bilshenz-desk-api >/dev/null

echo "==> Release gate"
cd "$APP_DIR/binance_trading_system/python"
.venv/bin/python run_all_tests.py > "$LOG_DIR/install-tests.log" 2>&1 || {
  echo "TESTS FAILED. See $LOG_DIR/install-tests.log. Do not start the bot."
  exit 1
}
tail -1 "$LOG_DIR/install-tests.log"

cat <<'NEXT'

INSTALL OK. The bot is not running and trading is off.
Next: sudo bash /opt/bilshenz/deploy/oracle/preflight.sh
NEXT
