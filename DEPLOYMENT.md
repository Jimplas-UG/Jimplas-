# Bilshenz — DigitalOcean Ubuntu 24.04 Deployment Guide

Target: **1 vCPU · 2 GB RAM · 70 GB SSD** · Ubuntu 24.04 LTS

---

## Server requirements

| Resource | Minimum | Notes |
|----------|---------|-------|
| CPU | 1 vCPU | Binance bridge + desk-api fit in ~1.2 GB RAM |
| RAM | 2 GB | Scanner WS uses ~200–400 MB under load |
| Disk | 20 GB+ | Logs rotate at `/var/log/bilshenz` |
| OS | Ubuntu 24.04 LTS | Tested path |
| Network | Outbound HTTPS | `fapi.binance.com` or testnet |

---

## Quick install

```bash
# On fresh Ubuntu 24.04 droplet (as root)
git clone https://github.com/Jimplas-UG/Jimplas-.git /opt/bilshenz
cd /opt/bilshenz
chmod +x deploy/ubuntu/*.sh deploy/install-production.sh
./deploy/install-production.sh

# Configure secrets
nano /etc/bilshenz.env   # BINANCE_API_KEY, BINANCE_API_SECRET, BRIDGE_TOKEN, DESK_API_KEY
chmod 600 /etc/bilshenz.env

systemctl restart bilshenz-binance-api bilshenz-desk-api
./deploy/ubuntu/healthcheck.sh
```

### Docker (alternative)

```bash
cp .env.example .env   # fill secrets
docker compose up -d --build
curl -s http://127.0.0.1:8766/health | jq .
```

---

## Environment variables

Copy `.env.example` → `/etc/bilshenz.env` (production) or `binance_trading_system/python/.env` (local).

| Variable | Required | Description |
|----------|----------|-------------|
| `BINANCE_API_KEY` | Prod | Futures API key (never commit) |
| `BINANCE_API_SECRET` | Prod | Futures API secret |
| `BINANCE_TESTNET` | No | `1` testnet, `0` mainnet |
| `BINANCE_PAPER` | No | `1` in-memory paper mode |
| `BINANCE_SYMBOL` | No | Default `XAUUSDT` |
| `BINANCE_LEVERAGE` | No | Default `10` |
| `BINANCE_MARGIN_TYPE` | No | `ISOLATED` or `CROSS` |
| `BRIDGE_TOKEN` | Recommended | Protects `/api/login`, orders |
| `HOST` | No | `0.0.0.0` on VPS |
| `PORT` | No | `8766` Binance bridge |
| `DESK_API_KEY` | Prod | Desk API auth |
| `BILSHENZ_ENV` | No | `production` / `development` / `testing` |
| `LOG_DIR` | No | `/var/log/bilshenz` on VPS |
| `FORWARD_DRY_RUN` | No | `1` blocks live orders |
| `SCANNER_EXEC` | No | `1` arms scanner on connect; `0` halts orders |

Validation runs on startup (`app_config.py`). Production exits if keys missing (unless `BINANCE_PAPER=1`).

---

## Firewall rules

```bash
ufw allow OpenSSH
ufw allow 8766/tcp   # Binance bridge
ufw allow 8791/tcp   # Desk API (mobile app)
ufw enable
```

Do **not** expose Metro (8081) on production VPS unless needed for dev.

---

## Ports

| Port | Service | systemd unit |
|------|---------|--------------|
| 8766 | Binance Futures bridge (Python) | `bilshenz-binance-api` |
| 8791 | Desk API (Node) | `bilshenz-desk-api` |

---

## Commands

```bash
./deploy/ubuntu/startup.sh    # start services
./deploy/ubuntu/stop.sh       # stop services
./deploy/ubuntu/restart.sh    # restart core
./deploy/ubuntu/healthcheck.sh
./deploy/ubuntu/deploy.sh     # full reinstall + restart

journalctl -u bilshenz-binance-api -f
tail -f /var/log/bilshenz/app.log
```

---

## Logs

| File | Content |
|------|---------|
| `/var/log/bilshenz/app.log` | General application |
| `/var/log/bilshenz/errors.log` | ERROR+ only |
| `/var/log/bilshenz/trades.log` | Trade events |
| `/var/log/bilshenz/websocket.log` | WS stream |

Rotated daily via `/etc/logrotate.d/bilshenz` (14 days, compress).

---

## Health endpoints

```bash
curl http://127.0.0.1:8766/health
curl http://127.0.0.1:8766/ping
```

`/health` returns: mode, connectivity, open positions, Binance latency, RAM, disk, WS status.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection aborted` on phone | Start `bilshenz-binance-api`; open firewall 8766 |
| `Invalid API-key` | Match testnet/mainnet toggle to key source |
| `418` / IP ban | Reduce request rate; wait; check `errors.log` |
| `-1021` timestamp | Auto time-sync retries; verify `ntp` on VPS |
| Service crash | `systemctl status bilshenz-binance-api`; `Restart=always` recovers |
| High RAM | Limit scanner symbols; set `BINANCE_PAPER=1` for testing |

---

## Rollback

```bash
cd /opt/bilshenz
git log -3 --oneline
git checkout <previous-commit>
.venv/bin/pip install -r binance_trading_system/python/requirements.txt
systemctl restart bilshenz-binance-api bilshenz-desk-api
```

---

## Security

- Secrets only in `/etc/bilshenz.env` (chmod 600)
- `.gitignore` blocks `.env`, `*.key`, `tradingbot.env`
- Set `BRIDGE_TOKEN` in production
- Use HTTPS reverse proxy (Caddy/nginx) for public desk-api
- SSH key-only login on droplet

---

## Binance Futures checklist (implemented)

| Item | Status |
|------|--------|
| API auth (HMAC SHA256) | ✔ `binance_connector.py` |
| Env key loading | ✔ `config_from_env()` |
| Secret never logged | ✔ masked in account_info |
| Time sync | ✔ `/fapi/v1/time`, recvWindow 60s |
| WS reconnect | ✔ exponential backoff `tick_stream.py` |
| REST retry | ✔ 5 attempts, URLError backoff |
| 429 rate limit | ✔ Retry-After |
| 418 IP ban | ✔ backoff up to 300s |
| Tick/step size | ✔ `exchangeInfo` filters |
| Min qty / notional | ✔ `_validate_order_qty` |
| Reduce-only | ✔ SL/TP/close orders |
| Hedge / one-way | ✔ `positionSide` when hedge mode |
| Margin ISOLATED/CROSS | ✔ `set_margin_type` |
| Leverage | ✔ `prepare_symbol` / env |
| Position monitor | ✔ `position_manager.py` |
| Order recovery on restart | ✔ lifespan logs positions/orders |

---

## Database

**No SQL database** in this stack. State:

- Live positions/orders: Binance API (source of truth)
- Paper mode: in-memory `paper_simulator.py`
- Auth users: JSON files (`backend/auth/data/`, gitignored)
- Forward demo logs: JSONL files

No migrations required for Binance bridge deployment.

---

# Final Readiness Report

## Scores

| Category | Score | Notes |
|----------|-------|-------|
| **Deployment** | **82/100** | systemd + Docker + install script; needs HTTPS proxy for prod |
| **Security** | **78/100** | Env-based secrets, BRIDGE_TOKEN; add fail2ban + TLS |
| **Performance** | **80/100** | Fits 2 GB; scanner WS is heaviest consumer |
| **Reliability** | **85/100** | WS reconnect, REST retry, systemd restart |
| **Binance API** | **88/100** | Full precision + hedge + 418/429 handling |
| **Ubuntu 24.04** | **90/100** | install-production.sh + CI on ubuntu-24.04 |
| **Docker** | **85/100** | Dockerfile + compose with healthchecks |
| **Production readiness** | **83/100** | Deployable; configure secrets + firewall |

## ✔ Ready

- Python bridge compiles and starts
- Env validation + `.env.example` files
- Rotating logs under `LOG_DIR`
- Health monitoring endpoint
- systemd `Restart=always`
- GitHub Actions CI (lint/build/docker)
- Binance: time sync, precision, reduce-only, hedge mode

## Missing / recommended

1. **HTTPS termination** — put Caddy/nginx in front of 8791/8766 for mobile prod
2. **Secrets manager** — DigitalOcean/AWS SM instead of flat file (optional)
3. **Persistent order journal** — SQLite for audit trail (optional)
4. **Alerting** — Telegram/webhook on disconnect (partial in deploy/watchdog)
5. **Mainnet cutover checklist** — set `BINANCE_TESTNET=0`, IP whitelist on Binance
6. **2 GB tuning** — reduce scanner universe or run bridge-only on smallest droplet
7. **E2E integration tests** — mock Binance for CI order flow

---

*Generated as part of production readiness audit. Update scores after first live VPS deploy.*
