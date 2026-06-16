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

## Binance Futures live trading

1. On PC: `cd binance_trading_system\python` → `python main.py` (port **8766**).
2. App env: `EXPO_PUBLIC_BROKER_MODE=binance` and `EXPO_PUBLIC_BINANCE_API_URL=http://YOUR_PC_IP:8766`.
3. Profile → API key + secret → **Connect Live** (or Testnet).
4. **AUTO-EXECUTE SIGNALS** sends gated orders when connected; otherwise tap **EXEC** on the Trade tab.

Public **XAUUSDT** quotes load without login. Orders require API keys with Futures + Read enabled (withdrawals off).

## Binance paper backtest

1. Start the Binance bridge and connect in Profile (for real M30 history).
2. Profile → run mode **BINANCE PAPER BT**.
3. Turn **PAPER AUTO-EXEC (BACKTEST)** ON to journal signals on each replay bar — no orders sent.
