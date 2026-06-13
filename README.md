# Bilshenz (bsv3)

Project layout after frontend/backend split:

| Folder | Purpose |
|--------|---------|
| **`frontend/`** | Expo Go mobile/web UI |
| **`backend/`** | Strategy engine, desk API, backtests |
| **`binance_trading_system/`** | Binance Futures Python API (port 8766) |
| **`mt5_trading_system/`** | Python MT5 API (legacy, port 8765) |
| **`myapp/`** | Legacy folder — use `frontend/` instead |

## Broker modes

Set `EXPO_PUBLIC_BROKER_MODE` / `BROKER_MODE`:

| Mode | Execution |
|------|-----------|
| `mt5` | MetaTrader 5 (default) |
| `binance` | Binance USD-M Futures testnet/live |
| `paper` | Simulated fills (`BINANCE_PAPER=1`) |

See `docs/BINANCE_DEPLOYMENT.md` and `docs/BINANCE_MIGRATION_PLAN.md`.

## Quick start

**1. Backend (strategy server)**

```powershell
cd backend
npm install
$env:DESK_API_KEY = "your-secret"
npm run desk-api
```

**2. Frontend (Expo app)**

```powershell
cd frontend
npm install
$env:EXPO_PUBLIC_DESK_REMOTE = "1"
$env:EXPO_PUBLIC_DESK_API_URL = "http://YOUR_LAN_IP:8791"
$env:EXPO_PUBLIC_DESK_API_KEY = "your-secret"
npm start
```

From repo root you can also run `npm start` (delegates to `frontend/`).

If `expo start` fails with `TypeError: fetch failed`, Metro is usually fine — the CLI could not reach expo.dev. `npm start` sets `EXPO_OFFLINE=1` automatically; or run `npx expo start --offline` from `frontend/`.

For local dev with full INTEL panels, omit `EXPO_PUBLIC_DESK_REMOTE` — Metro loads the engine from `../backend/engine`.

See `frontend/README.md` and `backend/README.md` for details.
