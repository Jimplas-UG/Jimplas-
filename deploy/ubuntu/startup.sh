#!/usr/bin/env bash
# Start all Bilshenz services (systemd)
set -euo pipefail
systemctl start bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || true
systemctl start bilshenz-binance-api bilshenz-desk-api
echo "Started. Check: ./deploy/ubuntu/healthcheck.sh"
