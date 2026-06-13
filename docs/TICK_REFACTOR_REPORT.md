# BSV3.2 Tick Refactor Report

**Date:** 2026-06-13  
**Scope:** Pip/lot → tick/contract conversion at execution + UI boundary  
**Strategy engine:** UNCHANGED (frozen — `pipSize` = strategy tick 0.1 for XAU)

## Summary

BSV3.2 now uses a **tick-based execution layer** for Binance Futures while preserving **identical strategy math**. Legacy `pip` names in the frozen engine map 1:1 to strategy ticks (`pipSize 0.1` → 100 pips = 100 ticks = $10.00 price distance on XAU).

## Architecture

```
Frozen engine (pipSize, *Pips config)  →  unchanged signals/SL/TP prices
         ↓
tickUnits.ts / tickUnits.js            →  tick distance + contract qty
         ↓
Binance bridge                         →  exchange tick_size + step_size normalization
         ↓
Expo UI (Binance mode)                 →  Ticks / Contract Qty labels
```

## Files Changed

| File | Change |
|------|--------|
| `backend/broker/tickUnits.ts` | **NEW** — tick math, risk verify, price normalize |
| `backend/broker/quantityMath.ts` | `slDistanceTicks`, aliases |
| `backend/broker/binanceFuturesApi.ts` | Normalize SL/TP to exchange tick grid |
| `frontend/lib/tickUnits.js` | **NEW** — tick sizing helpers |
| `frontend/lib/tickDisplay.js` | **NEW** — UI labels (Contract Qty, ticks) |
| `frontend/utils/riskSizing.js` | Tick-based sizing + contract quantity |
| `frontend/security/deskConstants.js` | `DISPLAY_TICK_SIZE` |
| `frontend/App.js` | Binance UI labels (qty, ticks, BE) |
| `binance_trading_system/python/binance_connector.py` | Symbol spec: tick_size, min_qty, env `*_TICKS` |
| `binance_trading_system/python/position_manager.py` | Tick-based BE/trail + BE-once guard |
| `backend/scripts/run-tick-refactor-audit.ts` | **NEW** — validation |
| `backend/package.json` | `audit:tick-refactor` script |

## Risk Model (Preserved)

| Before (MT5) | After (Binance) |
|--------------|-----------------|
| Risk $ = equity × 1% | Same |
| SL distance in pips | SL distance in **strategy ticks** (same number) |
| Lots = risk$ ÷ (ticks × $/tick/lot) | **Qty = risk$ ÷ \|entry−sl\|** |
| RR from TP ticks ÷ SL ticks | Same ratio |

## Remaining MT5 Dependencies

| Component | Status |
|-----------|--------|
| `backend/engine/*` | Frozen — uses pipSize internally |
| `mt5_trading_system/` | Legacy stack — correct MT5 vocabulary |
| `frontend/components/Mt5BridgePanel.js` | Active when `BROKER_MODE=mt5` |
| `backend/broker/mt5PythonApi.ts` | Unchanged MT5 path |
| `executeBrokerRoutes` | Dual path: `useMt5` + `useBinance` |

## Remaining Pip References (Expected)

| Location | Why kept |
|----------|----------|
| `backend/engine/*.ts` (15 files) | **Frozen strategy** — hash-locked |
| `frozen-manifest.json` | `pipSize`, `*Pips` config keys |
| `frontend/App.js` (engine display) | `atrPips`, `bullPips` from desk snapshot |
| `riskSizing.js` aliases | `structuralSlPips`, `slPips` backward compat |
| `binance_connector.py` | `be_trigger_pips` env alias → tick semantics |

**No database schema** exists — journals are JSON files; field names unchanged for history compatibility.

## Binance Futures Compatibility

| Requirement | Status |
|-------------|----------|
| Exchange tick size | `symbol_spec.tick_size` from `exchangeInfo` |
| Step size / min qty | `step_size`, `min_qty` |
| Price normalization | `normalizeOrderPrices()` on orders |
| Contract quantity | `quantityFromRiskUsd()` |
| BE @ +18 ticks | `BINANCE_BE_TRIGGER_TICKS` (alias `*_PIPS`) |
| Trailing @ 25/15 ticks | `BINANCE_TRAIL_*_TICKS` |
| FORWARD_DRY_RUN guard | Python `/api/order` |

## Validation

```powershell
cd backend
npm run audit:tick-refactor
```

Checks:
1. 1% risk preserved within 0.5%
2. Step-size compliance
3. 100 legacy pips = 100 strategy ticks
4. Execution layer scan

## Rollback

Set `EXPO_PUBLIC_BROKER_MODE=mt5` — MT5 lot path unchanged.

## Next Steps (Optional)

1. Rename desk snapshot fields `atrPips` → `atrTicks` (requires engine unfreeze + manifest regen)
2. Update backtest scripts to report ticks in output prose
3. Add unit tests for `position_manager` BE trigger at exactly 18 ticks
