# Binance Futures Deployment Guide (BSV3.2)

## Architecture

```
Expo App  →  desk-api :8791  →  /v1/binance/*  →  Binance Python API :8766  →  Binance Futures
                ↓
         backend/engine (unchanged — frozen strategy)
```

Strategy logic is **not** modified. Only the execution transport layer changed.

## Quick Start (Windows)

### One command — Binance bridge + desk-api

```powershell
cd backend
$env:DESK_API_KEY = "your-secret"
$env:BINANCE_PAPER = "1"          # paper fills, no API keys needed
npm run start:full:paper
```

Or with testnet keys:

```powershell
cd binance_trading_system\python
$env:BINANCE_API_KEY = "your-key"
$env:BINANCE_API_SECRET = "your-secret"
$env:BINANCE_TESTNET = "1"
cd ..\..\backend
$env:DESK_API_KEY = "your-secret"
npm run start:full
```

### Manual (3 processes)

#### 1. Binance Python bridge

```powershell
cd binance_trading_system\python
$env:BINANCE_API_KEY = "your-key"
$env:BINANCE_API_SECRET = "your-secret"
$env:BINANCE_TESTNET = "1"
$env:BINANCE_SYMBOL = "XAUUSDT"
.\start-api.ps1
```

**Paper mode (no API keys):**

```powershell
$env:BINANCE_PAPER = "1"
$env:EXPO_PUBLIC_BROKER_MODE = "paper"
.\start-api.ps1
```

### 2. Desk API

```powershell
cd backend
$env:DESK_API_KEY = "your-secret"
$env:BINANCE_API_URL = "http://127.0.0.1:8766"
npm run desk-api
```

### 3. Expo frontend (real backend — not mock)

```powershell
cd frontend
$env:EXPO_PUBLIC_DEV_PREVIEW = "0"
$env:EXPO_PUBLIC_MOCK_API = "0"
$env:EXPO_PUBLIC_BROKER_MODE = "binance"
$env:EXPO_PUBLIC_DESK_REMOTE = "1"
$env:EXPO_PUBLIC_DESK_API_URL = "http://YOUR_LAN_IP:8791"
$env:EXPO_PUBLIC_DESK_API_KEY = "your-secret"
$env:EXPO_PUBLIC_BINANCE_API_URL = "http://YOUR_LAN_IP:8791/v1/binance"
npm start
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BROKER_MODE` | `mt5` | `mt5` \| `binance` \| `paper` (forward-demo) |
| `BINANCE_API_KEY` | — | Futures API key |
| `BINANCE_API_SECRET` | — | Futures API secret |
| `BINANCE_TESTNET` | `1` | `1` = testnet, `0` = mainnet |
| `BINANCE_PAPER` | `0` | `1` = simulated fills |
| `BINANCE_SYMBOL` | `XAUUSDT` | Perpetual symbol |
| `BINANCE_LEVERAGE` | `10` | Max leverage |
| `BINANCE_MARGIN_TYPE` | `ISOLATED` | `ISOLATED` or `CROSSED` |
| `BINANCE_API_URL` | `http://127.0.0.1:8766` | Python bridge URL |
| `BINANCE_BE_TRIGGER_PIPS` | `18` | Breakeven trigger |
| `BINANCE_BE_OFFSET_PIPS` | `12` | Breakeven SL offset |
| `BINANCE_TRAIL_START_PIPS` | `25` | Trailing start |
| `BINANCE_TRAIL_STEP_PIPS` | `15` | Trailing step |
| `EXPO_PUBLIC_BROKER_MODE` | `mt5` | Frontend broker selection |
| `EXPO_PUBLIC_BINANCE_API_URL` | desk proxy | Mobile Binance URL |
| `FORWARD_DRY_RUN` | `1` | Blocks live orders when `1` |

## Order Flow

1. `computeBilshenzSnapshot()` → trade signal (frozen engine)
2. `canExecuteTrade()` → gates (daily loss, spread, session, etc.)
3. `buildBrokerOrderIntent()` → `{ side, entry, sl, tp1 }`
4. `quantityForTrade()` → `qty = riskUsd / |entry − sl|`
5. `POST /api/order` → `MARKET` + `STOP_MARKET` + `TAKE_PROFIT_MARKET`
6. Position manager → breakeven + trailing (mirrors MT5 EA)

## Testing

```powershell
# Parity audit (MT5 vs Binance klines → same signals?)
cd backend
npm run audit:migration-parity

# Forward demo on Binance testnet
$env:BROKER_MODE = "binance"
$env:BINANCE_TESTNET = "1"
$env:FORWARD_DRY_RUN = "0"
npm run forward-demo:30d
```

## Rollback

Set `EXPO_PUBLIC_BROKER_MODE=mt5` and `BROKER_MODE=mt5`. MT5 paths are unchanged.

## Files Changed (execution layer only)

| Added | Purpose |
|-------|---------|
| `binance_trading_system/python/*` | Binance REST bridge |
| `backend/broker/binanceFuturesApi.ts` | TS client |
| `backend/broker/quantityMath.ts` | Tick/step rounding |
| `backend/src/binanceProxy.ts` | Desk proxy |
| `frontend/broker/binanceFuturesApi.js` | Mobile client |
| `frontend/hooks/useBinanceLiveFeed.js` | Market feed |
| `frontend/components/BinanceBridgePanel.js` | Profile UI |
| `backend/scripts/run-migration-parity-audit.ts` | Validation |

| Modified | Change |
|----------|--------|
| `backend/broker/executeBrokerRoutes.ts` | `useBinance` route |
| `backend/src/server.ts` | `/v1/binance/*` proxy |
| `frontend/App.js` | Broker mode switch |
| `frontend/utils/riskSizing.js` | `quantityForTrade()` |

**Not modified:** `backend/engine/*`, `frozenProduction.ts`
