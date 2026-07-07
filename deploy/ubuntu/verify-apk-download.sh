#!/usr/bin/env bash
# Verify APK download is reachable on desk-api :8791
set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-8791}"
BASE="http://${HOST}:${PORT}"

echo "==> $BASE/health"
curl -fsS --max-time 8 "$BASE/health" | head -c 200
echo ""

echo "==> $BASE/download"
META=$(curl -fsS --max-time 8 "$BASE/download")
echo "$META"

if echo "$META" | grep -q '"error":"unauthorized"'; then
  echo "FAIL: /download requires auth — deploy latest desk-api (git pull + restart)"
  exit 1
fi

if echo "$META" | grep -q '"ok":true'; then
  echo "==> $BASE/download/bilshenz.apk"
  CODE=$(curl -fsS -o /tmp/bilshenz-test.apk -w "%{http_code}" --max-time 60 "$BASE/download/bilshenz.apk")
  SZ=$(wc -c < /tmp/bilshenz-test.apk | tr -d ' ')
  echo "HTTP $CODE size=${SZ} bytes"
  if [[ "$CODE" == "200" && "$SZ" -gt 1000000 ]]; then
    echo "OK: APK download works"
    exit 0
  fi
  echo "FAIL: APK too small or bad HTTP code"
  exit 1
fi

if echo "$META" | grep -q 'apk_not_found'; then
  echo "WARN: route OK but APK missing — upload to /opt/bilshenz/frontend/dist/bilshenz-release.apk"
  exit 2
fi

echo "FAIL: unexpected /download response"
exit 1
