# BSV3.2 — MT5 → Binance Futures Migration Plan

**Status:** Audit complete · Implementation not started  
**Repository:** [Jimplas-UG/Jimplas-](https://github.com/Jimplas-UG/Jimplas-)  
**Strategy ID:** `bilshenz-xau-m30-v1` (frozen production)  
**Date:** 2026-06-13

---

## Executive Summary

BSV3.2 is a production-grade XAU M30 trading system with a **broker-agnostic strategy engine** (`backend/engine/`) and a **thin MT5 execution layer**. The migration replaces only the execution/transport layer while preserving 100% of signal, risk-gate, and geometry logic.

**Core principle:** Do not modify frozen signal source files. Add a parallel Binance broker adapter behind the existing `BrokerOrderIntent` contract.

---

## 1. Architecture Audit

### 1.1 System Layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│  FRONTEND (Expo)                                                        │
│  App.js · useBilshenzMarketEngine · useMt5LiveFeed · Mt5BridgePanel    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ POST /v1/desk/compute, /execute-gate
┌───────────────────────────────▼─────────────────────────────────────────┐
│  BACKEND DESK API (server.ts)                                           │
│  Strategy compute · execute gate · MT5 proxy (/v1/mt5/*)               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐    ┌──────────────────┐    ┌────────────────────┐
│ STRATEGY      │    │ RISK / GATES     │    │ EXECUTION          │
│ ENGINE        │    │                  │    │ (REPLACE)          │
│ backend/      │    │ tradeBot.ts      │    │ mt5PythonApi       │
│ engine/*      │    │ riskEngine.ts    │    │ executeBrokerRoutes│
│ FROZEN        │    │ safetyControls   │    │ mt5_connector.py   │
└───────────────┘    └──────────────────┘    └────────────────────┘
```

### 1.2 Strategy Engine (PRESERVE — DO NOT MODIFY)

| Component | File | Responsibility |
|-----------|------|----------------|
| Orchestrator | `backend/engine/bilshenzEngine.ts` | `computeBilshenzSnapshot()` — single output |
| **Production signals** | `backend/engine/jimplasFluiditySignalEngine.ts` | P1 breakout/retest, P2 wick fill, P3 session impulse |
| Legacy signals | `backend/engine/signalEngine.ts` | E1/E2/E3 (inactive when `usePineV5: true`) |
| Trade permission | `backend/engine/tradeBot.ts` | `buildTradeRecommendation()` — blocks, allowed |
| Session filter | `backend/engine/sessionEngine.ts` | NY: PRE-LONDON 19–23, LONDON 02–06, NY 07–12 |
| News filter | `backend/engine/blackoutEngine.ts` + UI toggles | Manual `newsActive`, `nfpBlackout` (no calendar API) |
| S/R structure | `backend/engine/srEngine.ts` | M30 pivot replay |
| RR / TP geometry | `backend/engine/tradeGeometry.ts` | TP clamp 14–32p, P3 fixed 2:1 RR |
| M15 exit (sim) | `backend/engine/m15AdverseExit.ts` | HALF_LOSS at 45% SL distance |
| Risk snapshot | `backend/engine/riskEngine.ts` | Spread, hostile exec, DXY, ATH, geo, chop |
| Execution hardening | `backend/engine/executionHardening.ts` | Regime, adaptive spread, trade quality |
| Signal throttle | `backend/engine/signalThrottle.ts` | Loss cooldown (legacy path) |
| Frozen config | `backend/strategy/frozenProduction.ts` | Hash-locked source + production tunables |

**Active path:** `usePineV5: true` → Jimplas Fluidity (not `pineV5SignalEngine.ts`).

### 1.3 Risk Engine & Position Sizing (PRESERVE LOGIC, ADAPT UNITS)

| Concern | Location | Default / Behavior |
|---------|----------|-------------------|
| Risk % tiers | `types.ts` | Normal 1%, Elevated 0.7%, Crisis 0.5%, Geo cap 0.5% |
| Sizing formula | `frontend/utils/riskSizing.js` | `lots = equity × riskPct / (sizingSlPips × usdPerPipPerLot)` |
| Fixed sizing SL | `journalSizingSlPips: 20` | Structural SL sent to broker; sizing uses 20p |
| Daily loss gate | `tradeBot.ts` | 3% from NY day-start equity |
| Max drawdown gate | `tradeBot.ts` | 15% from peak equity |
| Max daily trades | frozen | 3 |
| Hostile spread kill | `riskEngine.ts` | spread > baseline × 2.35 |
| API failsafe | `safetyControls.ts` | 8 consecutive failures → halt |
| Dry run | `FORWARD_DRY_RUN=1` | Blocks live orders |
| Duplicate bar guard | `safetyControls.ts` | One order per M30 bar |
| One position | `mt5_connector.py` | Same symbol + magic — **replicate on Binance** |

### 1.4 Entry Logic (PRESERVE)

| Setup | Trigger | SL | TP |
|-------|---------|----|----|
| **P1** | S/R breakout + retest, body/volume filters | Breakout extreme ± buffer | Next clean R/S, ATR-capped |
| **P2** | Wick void fill + M30 break | Prior bar extreme ± buffer | Void height or opposing S/R |
| **P3** | Session open impulse (London/NY) | Entry wick ± `p3SlBufferPips` | Fixed `p3RewardRisk` (2:1) |

Gates: session, news/NFP, spread, structure, DXY↑ blocks BUY, ATH zone, geo HIGH, trade quality score.

### 1.5 Exit Logic

| Layer | Mechanism |
|-------|-----------|
| **Journal / backtest** | Bar touch TP1 → WIN; bar touch SL → LOSS; M15 adverse → HALF_LOSS |
| **Live MT5 order** | SL + TP1 attached at market entry |
| **MT5 EA (standalone)** | `ManageTrailingAndBE()` — BE at 18p profit, offset 12p; trail at 25p start, 15p step |
| **Node engine live** | No post-fill management — advisory `m15EarlyExit` only |

**Partial TP:** Not implemented in live execution. UI shows TP2 and day-of-week rules as copy only. No broker partial close today.

### 1.6 Breakeven Logic (MIGRATE TO BINANCE POSITION MANAGER)

From `ExpertAdvisor.mq5` → `ManageTrailingAndBE()`:

```
IF profitPips >= 18 (InpBeTriggerPips):
  BUY:  SL → entry + 12 × pipSize (InpBeOffsetPips)
  SELL: SL → entry - 12 × pipSize
  (only move SL in favorable direction)

IF profitPips >= 25 (InpTrailStartPips):
  Trail SL by 15p (InpTrailStepPips) behind price
```

Config mirror: `beOffset: 1.2` in `types.ts` (= 12p at pipSize 0.1).

**Migration action:** Implement equivalent in Binance position monitor via `STOP_MARKET` order modification (not in strategy engine).

### 1.7 Take Profit Logic (PRESERVE)

- Engine computes TP1 via geometry clamp (14–32p reward range, frozen).
- Single TP1 sent to broker on entry.
- TP2 is display-only (next structure zone).

### 1.8 MT5 Integration Layer (REPLACE ENTIRELY)

| Path | Files | Role |
|------|-------|------|
| **A — Primary** | `mt5_trading_system/python/main.py`, `mt5_connector.py` | FastAPI :8765 — login, bars, tick, order, positions |
| **B — Desk proxy** | `backend/src/mt5Proxy.ts` | `/v1/mt5/*` → Python API |
| **C — TS/JS client** | `backend/broker/mt5PythonApi.ts`, `frontend/broker/mt5PythonApi.js` | HTTP client |
| **D — Routing** | `backend/broker/executeBrokerRoutes.ts`, `frontend/broker/executeBrokerRoutes.js` | Webhook + MT5 |
| **E — Intent** | `backend/broker/webhookBroker.ts`, `brokerTypes.ts` | `BrokerOrderIntent` contract |
| **F — Market feed** | `frontend/hooks/useMt5LiveFeed.js` | M30 bars, tick, account poll |
| **G — UI** | `frontend/components/Mt5BridgePanel.js`, `Mt5BridgeContext.js` | Login, test order |
| **H — Legacy** | `backend/mt5/bridge-server.mjs`, `PollBridgeEA.mq5` | Webhook queue (fixed lots) |
| **I — Native EA** | `mt5_trading_system/mql5/Experts/Bilshenz/ExpertAdvisor.mq5` | Standalone — **deprecate** |
| **J — Forward bot** | `backend/scripts/run-forward-demo-30d.ts` | Headless auto-exec loop |

**Current order flow:**
1. `buildBrokerOrderIntent(trade)` → `{ side, entry, sl, tp1, symbol, setup }`
2. `lotsForTrade()` → MT5 volume (0.01 step)
3. `POST /api/order` → market deal + SL/TP on position
4. Magic `77002002`, one-position check

---

## 2. Binance Futures Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  FRONTEND                                                               │
│  useBinanceLiveFeed.js · BinanceBridgePanel.js (new)                    │
│  executeBrokerRoutes.js → useBinance flag                               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  BACKEND DESK API                                                       │
│  /v1/binance/* proxy (new) · unchanged /v1/desk/*                     │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  BINANCE EXECUTION SERVICE (new)                                        │
│  binance_trading_system/python/ OR backend/broker/binanceFuturesApi.ts  │
│                                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────┐  │
│  │ REST Client │  │ User Stream  │  │ Position Manager            │  │
│  │ signed HMAC │  │ WS fills     │  │ BE · trail · SL/TP monitor  │  │
│  └─────────────┘  └──────────────┘  └─────────────────────────────┘  │
│                                                                         │
│  Modes: PAPER (sim fills) · TESTNET · LIVE                              │
└─────────────────────────────────────────────────────────────────────────┘
```

**Unchanged:** `backend/engine/*`, `buildTradeRecommendation`, `canExecuteTrade`, `safetyControls`, frozen hashes.

---

## 3. MT5 → Binance Concept Mapping

| MT5 | Binance USD-M Futures |
|-----|----------------------|
| `XAUUSD` / `XAUUSDm` | `XAUUSDT` perpetual |
| Lots (0.01 step) | `quantity` from `LOT_SIZE` filter |
| `pipSize: 0.1` | `tickSize` from `exchangeInfo` (e.g. 0.01) |
| `$12.50/pip/lot` | `qty × |entry - sl|` for USDT risk |
| Market + SL/TP on deal | `MARKET` + `STOP_MARKET` + `TAKE_PROFIT_MARKET` |
| `PositionModify` (BE/trail) | Cancel/replace stop orders or `TRAILING_STOP_MARKET` |
| `copy_rates_from_pos` M30 | `GET /fapi/v1/klines?interval=30m` |
| `account_info().equity` | `GET /fapi/v2/account` wallet + unrealized |
| Spread from tick | `GET /fapi/v1/ticker/bookTicker` bid-ask |
| Magic number | `clientOrderId` prefix `BSV32_` |
| One position | `GET /fapi/v2/positionRisk` filter `positionAmt != 0` |

---

## 4. Implementation Phases

### Phase 0 — Foundation (no live orders)
- [ ] Add `binance_trading_system/` or `backend/broker/binance/` module structure
- [ ] Environment config: testnet vs mainnet, paper mode
- [ ] `exchangeInfo` cache: tickSize, stepSize, minQty, maxQty
- [ ] Symbol spec endpoint mirroring MT5 `/api/symbol/XAUUSD`
- [ ] Read-only: balance, position, klines, book ticker

### Phase 1 — Market Data Adapter
- [ ] `fetchBinanceBarsM30()` → same `{ t, o, h, l, c }` shape as MT5
- [ ] `useBinanceLiveFeed.js` replacing `useMt5LiveFeed.js` (feature flag)
- [ ] Validate: run frozen snapshot on Binance klines vs MT5 klines — signals must match
- [ ] DXY/US10Y: keep external source (Yahoo/sim) — unchanged

### Phase 2 — Order Execution (Testnet)
- [ ] `postBinanceOrderFromIntent()` implementing:
  - `MARKET` entry (BUY/SELL)
  - `STOP_MARKET` at `intent.sl` (closePosition or reduceOnly)
  - `TAKE_PROFIT_MARKET` at `intent.tp1`
- [ ] Quantity: `computeBinanceQuantity(equity, riskPct, slDistance, symbolSpec)`
- [ ] Price rounding: `roundToTickSize(price, tickSize)`
- [ ] Qty rounding: `roundToStepSize(qty, stepSize)`
- [ ] Leverage/margin: set isolated + leverage via `/fapi/v1/leverage`
- [ ] Wire into `executeBrokerRoutes` with `useBinance` flag
- [ ] Liquidation safety: check margin ratio before order; reject if below threshold

### Phase 3 — Position Manager (BE + Trail)
- [ ] Background service: poll or user-stream position updates
- [ ] Port `ManageTrailingAndBE` rules (18p trigger, 12p offset, 25p trail start, 15p step)
- [ ] Implement via stop order cancel/replace (not strategy engine)
- [ ] M15 half-loss: optional advisory + manual close (match current Node behavior)

### Phase 4 — Paper Trading Mode
- [ ] In-memory fill simulator using book ticker
- [ ] Simulated SL/TP triggers on price tick
- [ ] Same `BrokerOrderIntent` path — no strategy changes
- [ ] Log to forward-demo event stream

### Phase 5 — Production Safety Integration
- [ ] `recordApiSuccess/Failure` for Binance REST errors
- [ ] Pass `equityRisk` from Binance account into desk `/compute` (fix frontend gap)
- [ ] Idempotency: `clientOrderId = BSV32_{barTime}_{side}`
- [ ] `FORWARD_DRY_RUN` respected for Binance path
- [ ] Daily loss / DD gates with live Binance equity

### Phase 6 — Validation Framework
- [ ] `scripts/run-migration-parity-audit.ts`:
  - Replay N days of M30 bars through engine (frozen config)
  - Compare MT5 historical decisions vs Binance-feed decisions
  - Flag any `anyBuy`/`anySell`/`trade.allowed` drift
- [ ] Side-by-side order intent diff (entry, sl, tp1, qty)
- [ ] Generate `docs/MIGRATION_REPORT.md` with pass/fail matrix
- [ ] Extend existing `run-forward-execution-audit.ts` for Binance broker tag

### Phase 7 — Frontend & Deployment
- [ ] `BinanceBridgePanel` (API key status, testnet toggle, test order)
- [ ] Update `App.js` broker selection: MT5 | Binance | Paper
- [ ] Deploy guide + env example
- [ ] Deprecate MT5 paths (keep behind flag for rollback)

---

## 5. Files to Create

| File | Purpose |
|------|---------|
| `binance_trading_system/python/main.py` | FastAPI mirror of MT5 API surface |
| `binance_trading_system/python/binance_connector.py` | Signed REST + WS |
| `binance_trading_system/python/position_manager.py` | BE + trail |
| `binance_trading_system/python/paper_simulator.py` | Paper fills |
| `backend/broker/binanceFuturesApi.ts` | TS client (desk + forward bot) |
| `backend/broker/binanceTypes.ts` | Order result types |
| `backend/broker/quantityMath.ts` | Tick/step rounding, risk→qty |
| `backend/src/binanceProxy.ts` | `/v1/binance/*` proxy |
| `frontend/broker/binanceFuturesApi.js` | Client mirror |
| `frontend/hooks/useBinanceLiveFeed.js` | Klines + account |
| `frontend/components/BinanceBridgePanel.js` | UI |
| `backend/scripts/run-migration-parity-audit.ts` | Validation |
| `docs/BINANCE_DEPLOYMENT.md` | Ops guide |
| `docs/MIGRATION_REPORT.md` | Generated after validation |
| `deploy/windows/tradingbot.env.example` | Add Binance vars |

## 6. Files to Modify (execution layer only)

| File | Change |
|------|--------|
| `backend/broker/executeBrokerRoutes.ts` | Add `useBinance` route |
| `frontend/broker/executeBrokerRoutes.js` | Same |
| `backend/src/server.ts` | Mount binance proxy |
| `frontend/App.js` | Broker mode, equityRisk to desk, Binance panel |
| `frontend/utils/riskSizing.js` | Add `quantityForTrade()` (keep `lotsForTrade` for MT5) |
| `backend/scripts/run-forward-demo-30d.ts` | Binance broker option |
| `frontend/.env.example` | Binance public vars |

## 7. Files NOT to Modify (frozen / strategy)

```
backend/engine/jimplasFluiditySignalEngine.ts
backend/engine/signalEngine.ts
backend/engine/tradeBot.ts          ← only if gate logic bug found
backend/engine/bilshenzEngine.ts
backend/engine/riskEngine.ts
backend/engine/tradeGeometry.ts
backend/engine/sessionEngine.ts
backend/strategy/frozenProduction.ts
```

If `tradeBot.ts` must change, re-hash frozen manifest and document deviation.

## 8. Environment Variables

```bash
# Binance Futures
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=1                    # 1=testnet, 0=mainnet
BINANCE_SYMBOL=XAUUSDT
BINANCE_LEVERAGE=10
BINANCE_MARGIN_TYPE=ISOLATED         # ISOLATED | CROSSED

# Execution mode
BROKER_MODE=binance                  # mt5 | binance | paper
BINANCE_PAPER=0                      # 1=simulated fills, no API orders

# Safety (existing)
FORWARD_DRY_RUN=1
MAX_DAILY_LOSS_PCT=3
MAX_API_FAILURES=8
SAFETY_STATE_PATH=

# Desk (existing)
DESK_API_KEY=
BINANCE_API_URL=http://127.0.0.1:8766  # Python service bind

# Frontend
EXPO_PUBLIC_BROKER_MODE=binance
EXPO_PUBLIC_BINANCE_API_URL=http://LAN_IP:8791/v1/binance
```

## 9. Risk & Liquidation Safety

1. **Pre-trade:** `availableBalance >= riskUsd × 2` (buffer)
2. **Post-trade:** Monitor `liquidationPrice` vs mark price — alert if distance < 3 × ATR
3. **Max leverage cap:** Configurable ceiling (default 10×)
4. **Reduce-only** on SL/TP orders
5. **Funding rate** logging (optional P&L adjustment in journal)

## 10. Testing Procedures

| Stage | Test | Pass Criteria |
|-------|------|---------------|
| Unit | `quantityMath` rounding | Matches Binance LOT_SIZE/TICK_SIZE |
| Unit | Risk 1% on $50k, 20p SL | Qty × SL distance ≈ $500 |
| Integration | Testnet market + SL + TP | Position opens, stops placed |
| Parity | 30d klines MT5 vs Binance | Zero signal drift |
| Parity | Order intent diff | entry/sl/tp1 within 1 tick |
| Paper | 5-day forward demo | Journal outcomes match sim |
| Safety | API failure injection | Failsafe at 8 failures |
| Safety | 3% daily loss | Orders blocked |
| Live | $min qty testnet | Fill logged, BE triggers at 18p |

## 11. Rollback Strategy

- `BROKER_MODE=mt5` restores current path
- MT5 files untouched during migration
- Binance service is additive parallel deployment

## 12. Known Gaps & Decisions

| Item | Current State | Migration Decision |
|------|---------------|-------------------|
| Partial TP | UI copy only | Phase 3+ optional; not required for parity |
| M15 half-loss live | Advisory only | Keep advisory; optional auto-close later |
| EA standalone signals | Legacy Pine E1/E2/E3 | Deprecate — Node engine is source of truth |
| `equityRisk` in mobile | Not passed to desk | **Fix** — required for DD gates |
| DXY/US10Y feed | External/sim | Unchanged |
| Funding fees | Not modeled | Add to journal reporting only |

---

## 13. Next Step

**Await approval of this plan**, then begin Phase 0 + Phase 1 (market data adapter + validation scaffold) without touching frozen strategy files.
