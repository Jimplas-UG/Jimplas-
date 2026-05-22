#!/bin/bash
# Full production setup — Ubuntu 22.04 (DigitalOcean)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bilshenz}"
REPO="${REPO:-https://github.com/Jimplas-UG/Jimplas-.git}"
BRANCH="${BRANCH:-main}"
TZ="${TZ:-America/New_York}"
DEPLOY_SRC="${DEPLOY_SRC:-/tmp/bilshenz-deploy}"

export DEBIAN_FRONTEND=noninteractive

echo "==> System update"
apt-get update -qq
apt-get upgrade -y -qq
timedatectl set-timezone "$TZ" || true

echo "==> Packages"
apt-get install -y -qq \
  git curl ca-certificates ufw python3 python3-pip python3-venv \
  screen tmux htop logrotate fail2ban

echo "==> SSH hardening (keeps root password login)"
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-tradingbot.conf <<'SSHD'
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
MaxAuthTries 10
ClientAliveInterval 300
ClientAliveCountMax 3
SSHD
systemctl reload sshd || systemctl reload ssh || true

echo "==> Firewall (SSH only)"
ufw --force reset || true
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Logs"
mkdir -p /var/log/tradingbot
chmod 755 /var/log/tradingbot

if [[ -f "$DEPLOY_SRC/logrotate-tradingbot" ]]; then
  cp "$DEPLOY_SRC/logrotate-tradingbot" /etc/logrotate.d/tradingbot
elif [[ -f "$APP_DIR/deploy/logrotate/tradingbot" ]]; then
  cp "$APP_DIR/deploy/logrotate/tradingbot" /etc/logrotate.d/tradingbot
fi

echo "==> Python venv"
python3 -m venv /opt/tradingbot-venv
/opt/tradingbot-venv/bin/pip install --upgrade pip wheel
REQ="$APP_DIR/deploy/requirements.txt"
[[ -f "$DEPLOY_SRC/requirements.txt" ]] && REQ="$DEPLOY_SRC/requirements.txt"
if [[ -f "$REQ" ]]; then
  /opt/tradingbot-venv/bin/pip install -r "$REQ"
fi

echo "==> Node 20"
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Clone app"
mkdir -p "$APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --depth 1 -b "$BRANCH" "$REPO" "$APP_DIR"
else
  cd "$APP_DIR" && git fetch origin && git checkout "$BRANCH" && git pull --ff-only || true
fi

# Overlay deploy bundle uploaded from workstation
if [[ -d "$DEPLOY_SRC" ]]; then
  mkdir -p "$APP_DIR/deploy" "$APP_DIR/backend/production"
  cp -rf "$DEPLOY_SRC"/* "$APP_DIR/deploy/" 2>/dev/null || true
  [[ -d "$DEPLOY_SRC/production" ]] && cp -rf "$DEPLOY_SRC/production"/* "$APP_DIR/backend/production/" 2>/dev/null || true
fi

cd "$APP_DIR/backend"
npm ci 2>/dev/null || npm install
npm run strategy:freeze 2>/dev/null || true

if [[ ! -f /etc/tradingbot.env ]]; then
  cp "$APP_DIR/deploy/tradingbot.env.example" /etc/tradingbot.env
  chmod 600 /etc/tradingbot.env
fi
sed -i 's/\r$//' /etc/tradingbot.env 2>/dev/null || true
# Legacy name
ln -sf /etc/tradingbot.env /etc/bilshenz.env 2>/dev/null || true

echo "==> systemd"
for svc in bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog; do
  if [[ -f "$APP_DIR/deploy/systemd/${svc}.service" ]]; then
    sed -i 's|/etc/bilshenz.env|/etc/tradingbot.env|g' "$APP_DIR/deploy/systemd/${svc}.service" || true
    cp "$APP_DIR/deploy/systemd/${svc}.service" /etc/systemd/system/
  fi
done
if [[ -d "$DEPLOY_SRC/systemd" ]]; then
  cp "$DEPLOY_SRC/systemd/"*.service /etc/systemd/system/ 2>/dev/null || true
  sed -i 's|/etc/bilshenz.env|/etc/tradingbot.env|g' /etc/systemd/system/bilshenz-*.service 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || true

chmod +x "$APP_DIR/deploy/screen-fallback.sh" 2>/dev/null || true

systemctl restart bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || true

echo "SETUP_OK"
echo "Edit secrets: nano /etc/tradingbot.env"
echo "Status: systemctl status bilshenz-forward-bot"
