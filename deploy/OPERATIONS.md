# Trading bot operations (production VPS)

## Architecture

| Component | Where | Port |
|-----------|-------|------|
| Desk API | Ubuntu VPS | 8791 (localhost only; firewall blocks public) |
| Forward bot | Ubuntu VPS | — |
| MT5 + Exness | **Windows** | 8765 → set `MT5_API_URL` in `/etc/tradingbot.env` |

Ubuntu cannot run MetaTrader 5. Live orders require a Windows host with MT5 logged in and `start-api.ps1` running.

## Start / stop / restart

```bash
# Primary (systemd)
sudo systemctl start bilshenz-forward-bot
sudo systemctl stop bilshenz-forward-bot
sudo systemctl restart bilshenz-forward-bot

sudo systemctl start bilshenz-desk-api
sudo systemctl restart bilshenz-watchdog

# All services
sudo systemctl restart bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog
```

## Backup runtime (screen)

```bash
sudo /opt/bilshenz/deploy/screen-fallback.sh
screen -r tradingbot    # attach
# Ctrl+A D to detach
```

## Logs

```bash
# Live combined bot log
sudo tail -f /var/log/tradingbot/forward-bot.log

# Structured JSONL
sudo tail -f /var/log/tradingbot/trades.jsonl
sudo tail -f /var/log/tradingbot/errors.jsonl
sudo tail -f /var/log/tradingbot/reconnect.jsonl
sudo tail -f /var/log/tradingbot/safety.jsonl

# Watchdog
sudo tail -f /var/log/tradingbot/watchdog.log
```

## Configuration (secrets)

```bash
sudo nano /etc/tradingbot.env
sudo systemctl restart bilshenz-forward-bot
```

Required: `DESK_API_KEY`, `MT5_API_URL`, set `FORWARD_DRY_RUN=0` only when ready for live orders.

Optional Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## Safety

- `MAX_DAILY_LOSS_PCT` — stops new trades for the NY day
- `MAX_API_FAILURES` — failsafe after repeated MT5 API errors
- Duplicate orders blocked per bar + idempotency key
- Clear failsafe: edit `/var/log/tradingbot/safety-state.json` and set `"failsafe": false`, or delete the file

## Health check

```bash
systemctl status bilshenz-forward-bot bilshenz-desk-api bilshenz-watchdog
curl -s http://127.0.0.1:8791/health
ufw status
```

## Deploy from Windows workstation

```powershell
cd c:\Users\Amoskole\bsv3
$env:VPS_HOST='209.97.177.33'
$env:VPS_PW='your-password'
pip install paramiko -q
python deploy/remote-deploy.py
```
