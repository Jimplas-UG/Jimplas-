#!/usr/bin/env bash
# Read-only checks from the Oracle instance. Sends no orders and prints no secrets.
#   sudo bash /opt/bilshenz/deploy/oracle/preflight.sh
set -uo pipefail

APP_DIR="/opt/bilshenz"
ENV_FILE="/etc/bilshenz.env"
PY="$APP_DIR/binance_trading_system/python/.venv/bin/python"
fail=0
ok() { echo "OK   $1"; }
bad() { echo "FAIL $1"; fail=1; }
warn() { echo "WARN $1"; }

env_val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }

echo "== Environment file"
if [[ -f "$ENV_FILE" ]]; then
  [[ "$(stat -c %a "$ENV_FILE")" == "600" ]] && ok "$ENV_FILE is mode 600" || bad "$ENV_FILE must be mode 600"
  for k in BINANCE_API_KEY BINANCE_API_SECRET BRIDGE_TOKEN DESK_API_KEY AUTH_JWT_SECRET SESSION_ENC_KEY; do
    [[ -n "$(env_val "$k")" ]] && ok "$k is set" || bad "$k is empty"
  done
  [[ "$(env_val SCANNER_EXEC)" == "0" ]] && ok "SCANNER_EXEC=0 (trading off)" || warn "SCANNER_EXEC is not 0: trading is armed"
  [[ "$(env_val BINANCE_TESTNET)" == "1" ]] && ok "testnet mode" || warn "BINANCE_TESTNET is not 1: this is MAINNET"
else
  bad "$ENV_FILE missing"
fi

echo "== Binance reachability from this IP"
for url in https://fapi.binance.com/fapi/v1/time https://testnet.binancefuture.com/fapi/v1/time; do
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url")"
  case "$code" in
    200) ok "$url" ;;
    451|403) bad "$url returned $code: Binance blocks this region. Rebuild in Frankfurt." ;;
    *) bad "$url returned $code" ;;
  esac
done

echo "== Market streams"
"$PY" - <<'PYCHECK'
import asyncio
import websockets

ROUTES = [
    "wss://stream.binancefuture.com/market/ws/!miniTicker@arr",
    "wss://fstream.binance.com/market/ws/!miniTicker@arr",
]


async def probe(url):
    try:
        async with websockets.connect(url, open_timeout=8, ping_interval=None, max_size=None) as ws:
            await asyncio.wait_for(ws.recv(), 10)
            print("OK  ", url)
    except Exception as e:
        print("FAIL", url, type(e).__name__)


async def main():
    for u in ROUTES:
        await probe(u)


asyncio.run(main())
PYCHECK

echo "== Clock"
skew="$("$PY" - <<'PYCLOCK'
import json, time, urllib.request
t = json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/time", timeout=10))["serverTime"]
print(abs(int(time.time() * 1000) - t))
PYCLOCK
)"
if [[ -n "$skew" && "$skew" -lt 1000 ]]; then ok "clock skew ${skew}ms"; else bad "clock skew ${skew:-unknown}ms"; fi

echo "== Frozen strategy"
cd "$APP_DIR/binance_trading_system/python" || exit 1
if "$PY" -c "import sys; sys.argv=['test_preflight.py']; import frozen_strategy as f; f.assert_frozen_contract(); print(f.STRATEGY_ID, f.STRATEGY_VARIANT)"; then
  ok "frozen contract"
else
  bad "frozen contract"
fi

echo "== Firewall"
for port in 8766 8791; do
  iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
    && ok "iptables allows $port" || bad "iptables does not allow $port"
done

echo
if [[ $fail -eq 0 ]]; then echo "PREFLIGHT PASSED"; else echo "PREFLIGHT FAILED"; fi
exit $fail
