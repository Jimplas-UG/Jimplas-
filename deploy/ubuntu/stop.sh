#!/usr/bin/env bash
set -euo pipefail
systemctl stop bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null || true
echo "Stopped Bilshenz services."
