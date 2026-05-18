# Bilshenz (bsv3)

Project layout after frontend/backend split:

| Folder | Purpose |
|--------|---------|
| **`frontend/`** | Expo Go mobile/web UI |
| **`backend/`** | Strategy engine, desk API, backtests, MT5 bridge |
| **`mt5_trading_system/`** | Python MT5 API (unchanged) |
| **`myapp/`** | Legacy folder — use `frontend/` instead |

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

For local dev with full INTEL panels, omit `EXPO_PUBLIC_DESK_REMOTE` — Metro loads the engine from `../backend/engine`.

See `frontend/README.md` and `backend/README.md` for details.
