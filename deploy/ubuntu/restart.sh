#!/usr/bin/env bash
set -euo pipefail
systemctl restart bilshenz-binance-api bilshenz-desk-api
echo "Restarted binance-api + desk-api."
