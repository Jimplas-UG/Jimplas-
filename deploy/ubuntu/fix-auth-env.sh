#!/usr/bin/env bash
# Fix production auth secrets and restart desk-api
set -euo pipefail
ENV=/etc/bilshenz.env
touch "$ENV"
chmod 600 "$ENV"
grep -q '^PRODUCTION_MODE=' "$ENV" || echo 'PRODUCTION_MODE=1' >> "$ENV"
grep -q '^STRATEGY_FREEZE=' "$ENV" || echo 'STRATEGY_FREEZE=1' >> "$ENV"
if ! grep -q '^AUTH_JWT_SECRET=' "$ENV"; then
  echo "AUTH_JWT_SECRET=$(openssl rand -hex 32)" >> "$ENV"
  echo ADDED_AUTH_JWT_SECRET
else
  LEN=$(grep '^AUTH_JWT_SECRET=' "$ENV" | cut -d= -f2- | tr -d '\r\n' | wc -c)
  if [ "$LEN" -lt 32 ]; then
    sed -i "s|^AUTH_JWT_SECRET=.*|AUTH_JWT_SECRET=$(openssl rand -hex 32)|" "$ENV"
    echo ROTATED_SHORT_AUTH_JWT_SECRET
  else
    echo AUTH_JWT_SECRET_OK
  fi
fi
systemctl restart bilshenz-desk-api bilshenz-binance-api
sleep 3
curl -s --max-time 8 http://127.0.0.1:8791/health || true
echo
systemctl is-active bilshenz-desk-api bilshenz-binance-api
