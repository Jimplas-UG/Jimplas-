# Production deploy (DigitalOcean Ubuntu)

## Critical: MT5 is Windows-only

MetaTrader 5 + the Python `MetaTrader5` package **cannot run on Ubuntu**. This VPS runs:

- **Desk API** (8791) — strategy engine
- **Forward bot** — AUTO-EXEC via remote `MT5_API_URL`
- **Watchdog** — health + MT5 reconnect alerts

**Exness login** happens on a **Windows** machine (your PC or a Windows VPS):

1. Install MT5 Exness, log in to **production** account
2. Run `mt5_trading_system/python/start-api.ps1` (port 8765)
3. Open firewall port **8765** on Windows for VPS IP `68.183.35.165`
4. Set on Linux: `MT5_API_URL=http://YOUR_WINDOWS_PUBLIC_IP:8765` in `/etc/bilshenz.env`

Without Windows MT5, the VPS bot **cannot place Exness orders**.

## One-shot install on VPS

```bash
ssh root@68.183.35.165
curl -fsSL https://raw.githubusercontent.com/Jimplas-UG/Jimplas-/main/deploy/install-production.sh | bash
nano /etc/bilshenz.env   # set DESK_API_KEY, MT5_API_URL
systemctl restart bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog
curl http://127.0.0.1:8791/health
```

## Health

- `http://68.183.35.165:8791/health` — desk-api
- Logs: `/var/log/bilshenz/*.log`
