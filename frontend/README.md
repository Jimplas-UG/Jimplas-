# Bilshenz Frontend (Expo)

Trader UI only — no strategy engine in this folder. Strategy runs in `../backend`.

## Run (production-style, engine on server)

```powershell
cd ..\backend
$env:DESK_API_KEY = "your-secret"
npm run desk-api

cd ..\frontend
$env:EXPO_PUBLIC_DESK_REMOTE = "1"
$env:EXPO_PUBLIC_DESK_API_URL = "http://YOUR_PC_LAN_IP:8791"
$env:EXPO_PUBLIC_DESK_API_KEY = "your-secret"
npm install
npm start
```

## Run (local dev with full INTEL panels)

```powershell
cd frontend
# Do not set EXPO_PUBLIC_DESK_REMOTE — Metro loads engine from ../backend/engine
npm start
```

## MT5 live feed

Start Python MT5 API from repo root: `cd ..\mt5_trading_system\python` (see that folder’s README), then connect in the app Profile tab.
