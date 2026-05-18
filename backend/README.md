# Bilshenz Backend

Strategy engine, desk API, backtests, MT5 bridge, and broker execution logic.

## Desk API

```powershell
cd backend
npm install
$env:DESK_API_KEY = "your-secret"
npm run desk-api
```

Listens on `http://0.0.0.0:8791` (override with `DESK_API_PORT`).

## Backtests

```powershell
npm run backtest:xau12mo:realistic
```

Requires MT5 Python API at `http://127.0.0.1:8765` when using `--mt5-api`.

## Layout

| Path | Role |
|------|------|
| `engine/` | Bilshenz strategy |
| `broker/` | Execution gates, MT5/Telegram |
| `src/server.ts` | Private desk HTTP API |
| `scripts/` | Audits and backtests |
| `mt5/` | Node bridge + EA docs |
