# Frozen production strategy

Signal generation and optimization parameters are **locked** for forward demo and live validation.

## Lock scope

- **Config:** `productionFrozenConfig()` in `frozenProduction.ts` (live profile + execution hardening)
- **Source files:** SHA-256 hashes in `frozen-manifest.json` for all files in `FROZEN_SIGNAL_SOURCE_FILES`
- **Blocked tuning keys:** P1/P2 thresholds, TP clamps, quality floors, daily caps, pivot/left-scan params, etc.

## Commands

```bash
cd backend
npm run strategy:freeze    # Regenerate frozen-manifest.json after intentional strategy release
npm run strategy:verify    # CI / pre-deploy hash check
```

## Forward demo (30 days)

1. Freeze: `npm run strategy:freeze`
2. Start stack with freeze enforced:
   - `npm run desk-api:frozen` (port 8791)
   - `npm run mt5-api` (port 8765)
   - Expo app: LIVE SIM + AUTO-EXEC on **Exness demo**
3. **No parameter changes** in Profile (spread is live quote only).
4. Execution events append to `backend/validation/data/forward-demo-log.jsonl`
5. After 30 days: `npm run audit:forward-execution`

## Logged fields

| Field | Source |
|-------|--------|
| Signal timestamp | `SIGNAL` events from desk / AUTO-EXEC |
| Intended fill | `ORDER_INTENT` / engine entry |
| Actual fill | MT5 `fill_price` |
| Slippage | `slippage_pips` from bridge |
| Spread at execution | `spread_pips` from tick |
| Rejected orders | `ORDER_REJECTED` |
| Latency | `latency_ms` around `order_send` |
| Missed trades | `MISSED_TRADE` when gate blocks after signal |
| Equity drift | `EQUITY_SNAPSHOT` periodic |

## Alerts (audit)

- Win-rate drift > ±10% vs sim
- PF < 1.8 (min 5 live trades)
- DD > 135% of sim max DD
- Avg slippage > 2.5p
- Execution mismatch rate > 15%
