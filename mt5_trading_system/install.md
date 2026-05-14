# Bilshenz MT5 trading system — install & verification

This pack adds **native MQL5** (indicator + EA), a **Python MetaTrader5 REST bridge**, and **Expo UI** hooks. Strategy math is aligned with `myapp/engine` (TypeScript). **There is no `.pine` file in this repository**, so “exact Pine” parity cannot be certified—compare signals visually or export both to CSV for diff.

---

## 1. Folder layout (repo)

| Path | Role |
|------|------|
| `mt5_trading_system/mql5/Include/Bilshenz/BilshenzCore.mqh` | Shared S/R replay + P1–P3 signals |
| `mt5_trading_system/mql5/Indicators/Bilshenz/Indicator.mq5` | Chart indicator + dashboard labels |
| `mt5_trading_system/mql5/Experts/Bilshenz/ExpertAdvisor.mq5` | Auto-trading EA |
| `mt5_trading_system/python/` | FastAPI + `mt5_connector.py` |
| `myapp/components/Mt5BridgePanel.js` | Profile tab UI |

---

## 2. MetaTrader 5 — copy includes & compile

1. Install **MetaTrader 5** from your broker (e.g. Exness) and log in (**demo** first).
2. Open **data folder**: MT5 → **File → Open Data Folder**.
3. Copy **`Bilshenz`** folder from repo:
   - From: `mt5_trading_system/mql5/Include/Bilshenz/`
   - To: `<DataFolder>/MQL5/Include/Bilshenz/`
4. Copy **Indicator**:
   - From: `mt5_trading_system/mql5/Indicators/Bilshenz/Indicator.mq5`
   - To: `<DataFolder>/MQL5/Indicators/Bilshenz/Indicator.mq5` (create `Bilshenz` subfolder if needed)
5. Copy **EA**:
   - From: `mt5_trading_system/mql5/Experts/Bilshenz/ExpertAdvisor.mq5`
   - To: `<DataFolder>/MQL5/Experts/Bilshenz/ExpertAdvisor.mq5`
6. Open **MetaEditor**, open each `.mq5`, press **Compile** (F7). Fix any “cannot open include” by rechecking step 3 path (`#include <Bilshenz/BilshenzCore.mqh>`).
7. Attach **Indicator** to an **M30** chart of your symbol (e.g. `XAUUSD` / `XAUUSDm`).
8. For **EA**: enable **Algo Trading**, attach to **M30** chart, review **Inputs** (lots, SL pips, magic). **Use demo only** until validated.

### WebRequest / old bridge

The existing Node `myapp/mt5/bridge-server.mjs` + `PollBridgeEA.mq5` path is unchanged; this system adds **indicator/EA/Python** alongside it.

---

## 3. Symbol & pip size

Gold symbols differ by broker (`XAUUSD`, `XAUUSDm`, …). Inputs **`InpPipSize`** (default `0.1`) and zone widths must match your broker’s **point** definition. If arrows/levels look wrong, adjust **`InpPipSize`** and **`InpZoneHalfPips`** to match your Pine/TS calibration.

---

## 4. Python API (Windows + MT5 terminal)

**Requirements:** same machine as MT5, **64-bit Python**, `MetaTrader5` package (official).

```powershell
cd mt5_trading_system\python
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# Optional: path to terminal if non-standard
# $env:MT5_TERMINAL_PATH="C:\Program Files\MetaTrader 5"
$env:PORT=8765
python main.py
```

Health check: `http://127.0.0.1:8765/health`

### Endpoints

- `POST /api/login` — JSON `{ "login": 123456, "password": "…", "server": "Broker-Server" }`
- `POST /api/logout`
- `GET /api/status`
- `GET /api/tick/XAUUSD` (change symbol to match broker)
- `GET /api/positions`
- `POST /api/order` — `{ "symbol": "XAUUSD", "side": "BUY"|"SELL", "volume": 0.01, "sl": null, "tp": null }`
- `GET /api/logs?limit=50`

**Firewall:** allow inbound **8765** (or chosen `PORT`) for LAN access from phone running Expo.

---

## 5. Expo app UI

1. Set at build/dev time: **`EXPO_PUBLIC_MT5_API_URL=http://YOUR_PC_IP:8765`**
2. Open app → **Profile** → **MT5 PYTHON API** section: base URL, server, login, password → **CONNECT MT5**.
3. Manual **BUY/SELL** sends **0.01** lot via API (demo only recommended).

---

## 6. Verification (Part 5)

### A) TS 12-month backtest (already in repo)

From `myapp`:

```powershell
npx tsx scripts/run-xau-12mo-yahoo-backtest.ts
# or with MT5 export CSV:
npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --mt5-csv "C:\path\XAUUSD_M30.csv"
```

### B) MT5 Strategy Tester (EA)

1. MT5 → **View → Strategy Tester**
2. Expert: **ExpertAdvisor**
3. Symbol **XAUUSD** (or broker name), period **M30**, **Every tick based on real ticks** (or OHLC if data limited)
4. Date range ≈ **12 months**
5. Compare trade count / direction to TS backtest or TradingView—**expect differences** if feeds differ.

### C) Indicator vs Pine

Without Pine source, automated diff is not shipped. Export MT5 indicator signal times (manually note bar times) and compare to TV alert log, or export both to CSV.

---

## 7. Security

- Never commit real passwords. `.env` / OS env for `EXPO_PUBLIC_*` only as needed.
- REST API has **no auth** in this template—**bind to LAN** or add API key / reverse proxy before exposing publicly.

---

## 8. Known limits

- **Python `MetaTrader5`**: Windows-oriented; MT5 must be running and logged in.
- **MQL5 / TS parity**: same formulas as `signalEngine` / `replaySrBarByBar`, but floating-point, session time (GMT hour stub), and broker data can diverge from TradingView.
- **UI** does not yet drive the main Bilshenz engine price—**live chart data** still uses app sim unless you extend the bridge to push bars into `useBilshenzMarketEngine`.

---

## 9. Quick compile checklist

- [ ] `BilshenzCore.mqh` under `MQL5/Include/Bilshenz/`
- [ ] `Indicator.mq5` compiles (0 errors)
- [ ] `ExpertAdvisor.mq5` compiles (0 errors)
- [ ] `python main.py` + `/health` OK
- [ ] Expo Profile connects and shows balance / tick

When all checked, you are ready for **demo paper** testing on MT5.
