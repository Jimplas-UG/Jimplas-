MT5 + Bilshenz app — how “algo trading without pressing EXEC” works
====================================================================

The phone app NEVER talks to the MT5 terminal directly. MT5 only runs
scripts/EAs on your PC/VPS. Flow:

  [ App: AUTO-EXECUTE + webhook URL ]  --HTTPS POST JSON-->
  [ bridge-server.mjs on your PC/VPS ]  --plain text poll-->
  [ PollBridgeEA.mq5 attached to chart ]  --OrderSend-->
  [ Your broker ]

What YOU do
-----------
1) Copy mt5/PollBridgeEA.mq5 into MetaEditor, compile, attach to the
   symbol chart you trade (symbol in webhook must match broker name,
   e.g. XAUUSD vs XAUUSDm — set MT5_SYMBOL in bridge env if needed).

2) In MT5: enable **Algo Trading** (AutoTrading) on the toolbar.

3) Tools → Options → Expert Advisors → tick **Allow WebRequest for
   listed URL** and add the exact poll URL host (e.g. http://127.0.0.1).

4) On the same machine as MT5, run the bridge:
     set MT5_BRIDGE_SECRET=some-long-random-string
     set MT5_BRIDGE_PORT=8788
     node mt5/bridge-server.mjs

5) In the app Profile:
   - Webhook URL = http://YOUR_PC_LAN_IP:8788/webhook
     (same PC only: http://127.0.0.1:8788/webhook from phone won’t work
     unless you use a tunnel like ngrok — phone must reach the bridge.)
   - Optional: same secret in app env EXPO_PUBLIC_BROKER_WEBHOOK_SECRET
     (Bearer) and in EA poll URL ?key=...
   - Turn on **AUTO-EXECUTE SIGNALS** (live sim, webhook set).

6) Remote phone: the bridge must be reachable on the internet (VPS
   public IP, reverse proxy, or tunnel). Never expose /webhook without
   MT5_BRIDGE_SECRET set.

Risks
-----
Auto mode can send many real orders. Use demo account first, small lots,
and daily trade caps in the app. The EA uses market orders at current
price with SL/TP from the intent — tune SlippagePt and symbol names.

12-month engine backtest (IC Markets OHLC)
-------------------------------------------
IC Markets does not publish a free HTTP history API in this repo. To
backtest on **real IC / MT5 bars**, export CSV from MT5:

  View → Symbols → pick XAUUSD (or XAUUSDm etc.) → **Bars** tab →
  choose **M30** or **H1** → set the date range → **Request** →
  **Export Bars** (CSV).

Then from the `myapp` folder:

  npx tsx scripts/run-xau-12mo-yahoo-backtest.ts --mt5-csv "C:\path\to\export.csv"

Or: `set MT5_CSV=...` / `set IC_MARKETS_CSV=...` before the same command.

Optional: `set MT5_CSV_OFFSET_MS=-7200000` to shift all bar timestamps
if you need broker server time aligned with UTC for session logic.
