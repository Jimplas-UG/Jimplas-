#!/usr/bin/env bash
# Turn trading on or off on this server.
#   sudo bash arm-trading.sh off
#   sudo bash arm-trading.sh on --old-server-stopped --book-flat
# Two bots on one API key would double-trade the account, so "on" needs both confirmations.
set -euo pipefail

ENV_FILE="/etc/bilshenz.env"
MODE="${1:-}"
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

set_exec() {
  if grep -q '^SCANNER_EXEC=' "$ENV_FILE"; then
    sed -i "s/^SCANNER_EXEC=.*/SCANNER_EXEC=$1/" "$ENV_FILE"
  else
    echo "SCANNER_EXEC=$1" >> "$ENV_FILE"
  fi
}

case "$MODE" in
  off)
    set_exec 0
    ;;
  on)
    [[ " $* " == *" --old-server-stopped "* && " $* " == *" --book-flat "* ]] || {
      echo "Refused. Stop the old server and confirm no open positions, then pass:"
      echo "  --old-server-stopped --book-flat"
      exit 1
    }
    bash /opt/bilshenz/deploy/oracle/preflight.sh
    set_exec 1
    ;;
  *)
    echo "Usage: sudo bash arm-trading.sh on|off"
    exit 1
    ;;
esac

systemctl restart bilshenz-binance-api bilshenz-desk-api
sleep 5
bash /opt/bilshenz/deploy/ubuntu/healthcheck.sh || true
echo "SCANNER_EXEC=$(grep '^SCANNER_EXEC=' "$ENV_FILE" | cut -d= -f2)"
