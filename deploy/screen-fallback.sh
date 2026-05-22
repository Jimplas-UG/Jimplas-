#!/bin/bash
# Backup runtime if systemd is stopped — attach with: screen -r tradingbot
set -euo pipefail
SESSION=tradingbot
APP=/opt/bilshenz/backend
if screen -list | grep -q "\.${SESSION}"; then
  echo "Screen session '${SESSION}' already running"
  exit 0
fi
screen -dmS "$SESSION" bash -c "
  set -a
  source /etc/tradingbot.env
  set +a
  cd '$APP'
  exec npx tsx scripts/run-forward-demo-30d.ts >> /var/log/tradingbot/screen-bot.log 2>&1
"
echo "Started screen session: screen -r ${SESSION}"
