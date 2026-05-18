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

## Run (local dev with full INTEL panels on device)

```powershell
cd frontend
$env:EXPO_PUBLIC_DESK_LOCAL = "1"
npm start
```

Do **not** set `EXPO_PUBLIC_DESK_REMOTE=0` in Windows user env — it forces Metro to bundle `../backend/engine` on the phone and causes `@babel/runtime` / 500 errors in Expo Go. Default `npm start` uses the remote engine stub; run `desk-api` on your PC.

## MT5 paper backtest

1. Start MT5 + `mt5_trading_system/python/start-api.ps1` and connect in Profile.
2. Profile → run mode **MT5 PAPER BT** (when MT5 is connected).
3. Turn **PAPER AUTO-EXEC (BACKTEST)** ON to journal signals on each replay bar.
4. No orders are sent to MT5 — journal only. Use **LIVE SIM** + auto-exec for real/demo execution.

## MT5 live feed

Start Python MT5 API from repo root: `cd ..\mt5_trading_system\python` (see that folder’s README), then connect in the app Profile tab.
