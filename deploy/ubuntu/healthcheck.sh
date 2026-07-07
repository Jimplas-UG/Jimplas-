#!/usr/bin/env bash
# Health check — exit 0 when core services respond
set -euo pipefail
BINANCE_URL="${BINANCE_URL:-http://127.0.0.1:8766}"
DESK_URL="${DESK_URL:-http://127.0.0.1:8791}"

fail=0
check() {
  local name="$1" url="$2"
  if curl -fsS --max-time 8 "$url" >/dev/null; then
    echo "OK  $name  $url"
  else
    echo "FAIL $name  $url"
    fail=1
  fi
}

check "binance-api" "$BINANCE_URL/health"
check "desk-api" "$DESK_URL/health" 2>/dev/null || check "desk-api" "$DESK_URL/ping" 2>/dev/null || true

if curl -fsS --max-time 8 "$DESK_URL/download" 2>/dev/null | grep -q '"error":"unauthorized"'; then
  echo "FAIL apk-download  $DESK_URL/download (auth required — run deploy/ubuntu/VPS-PASTE-FIX-APK.sh)"
  fail=1
elif curl -fsS --max-time 8 "$DESK_URL/download" 2>/dev/null | grep -q '"ok":true'; then
  echo "OK  apk-download  $DESK_URL/download/bilshenz.apk"
else
  echo "WARN apk-download  route OK or APK not uploaded yet"
fi

if command -v systemctl &>/dev/null; then
  for svc in bilshenz-binance-api bilshenz-desk-api; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      echo "OK  systemd $svc"
    else
      echo "WARN systemd $svc not active"
    fi
  done
fi

free -h 2>/dev/null | head -2 || true
df -h / 2>/dev/null | tail -1 || true

exit $fail
