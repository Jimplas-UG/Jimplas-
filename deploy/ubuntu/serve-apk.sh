#!/usr/bin/env bash
# One-shot: deploy APK download route + verify (run on VPS as root).
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
cd "$APP_DIR"

if [[ -d .git ]]; then
  git fetch origin
  git checkout main
  git pull --ff-only origin main || true
fi

node "$APP_DIR/deploy/ubuntu/patch-desk-apk-route.mjs"
mkdir -p "$APP_DIR/frontend/dist"
chmod 755 "$APP_DIR/frontend/dist"

systemctl restart bilshenz-desk-api
sleep 2

bash "$APP_DIR/deploy/ubuntu/verify-apk-download.sh" 127.0.0.1 8791 || true
PUB=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo "Phone install URL: http://${PUB}:8791/download/bilshenz.apk"
