#!/usr/bin/env python3
"""Sep23-25 vs last3 — use live bridge session keys + log stream. READ-ONLY."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")

BASE_DAYS = {"2026-09-23", "2026-09-24", "2026-09-25"}
now = datetime.now(timezone.utc)
LAST3 = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(0, 3)}
print("BASE", sorted(BASE_DAYS), "LAST3", sorted(LAST3))


def load_env():
    env = {}
    for l in Path("/etc/bilshenz.env").read_text().splitlines():
        if "=" in l and not l.startswith("#"):
            k, v = l.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def bridge_get(path: str):
    env = load_env()
    tok = env.get("BRIDGE_TOKEN", "")
    req = urllib.request.Request(
        f"http://127.0.0.1:8766{path}",
        headers={"Authorization": f"Bearer {tok}", "X-Bridge-Token": tok},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def live_keys():
    """Prefer running connector session; fall back to decrypted store / env."""
    env = load_env()
    key = env.get("BINANCE_API_KEY", "")
    secret = env.get("BINANCE_API_SECRET", "")
    testnet = env.get("BINANCE_TESTNET", "1") in ("1", "true", "True", "yes", "on")
    # Try session helper used by bridge
    try:
        from session_store import load_binance_session  # type: ignore

        sess = load_binance_session() or {}
        if sess.get("api_key") and sess.get("api_secret"):
            key = sess["api_key"]
            secret = sess["api_secret"]
            if "testnet" in sess:
                testnet = bool(sess["testnet"])
            print("KEYS_FROM session_store")
            return key, secret, testnet
    except Exception as e:
        print("session_store_miss", type(e).__name__, e)
    try:
        from credential_store import load_credentials  # type: ignore

        cred = load_credentials() or {}
        if cred.get("api_key"):
            key = cred["api_key"]
            secret = cred["api_secret"]
            testnet = bool(cred.get("testnet", testnet))
            print("KEYS_FROM credential_store")
            return key, secret, testnet
    except Exception as e:
        print("credential_store_miss", type(e).__name__, e)
    # Ask running bridge status for mode, then use whatever env has after probing account via bridge
    print("KEYS_FROM env lens", len(key), len(secret), "testnet", testnet)
    return key, secret, testnet


def signed_get(base, key, secret, path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 60000
    q = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{q}&signature={sig}"
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def pull_income(base, key, secret, income_type, start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + 5 * 24 * 3600 * 1000, end_ms)
        try:
            part = signed_get(
                base,
                key,
                secret,
                "/fapi/v1/income",
                {
                    "incomeType": income_type,
                    "startTime": cursor,
                    "endTime": chunk_end,
                    "limit": 1000,
                },
            )
        except Exception as e:
            print(income_type, "ERR", e)
            break
        if not part:
            cursor = chunk_end + 1
            continue
        rows.extend(part)
        last = max(int(x.get("time") or 0) for x in part)
        cursor = chunk_end + 1 if last <= cursor or len(part) < 1000 else last + 1
    return rows


def bucket(day: str):
    if day in BASE_DAYS:
        return "SEP23_25"
    if day in LAST3:
        return "LAST3"
    return None


print("\n=== BRIDGE CALENDAR ===")
try:
    cal = bridge_get("/api/calendar?days=20")
    days = cal.get("days") or cal.get("calendar") or []
    print("calendar_ok", cal.get("ok"), "stale", cal.get("stale"), "n", len(days))
    for d in days:
        if not isinstance(d, dict):
            continue
        day = str(d.get("date") or d.get("day") or "")
        tag = ""
        if day in BASE_DAYS:
            tag = " [BASE]"
        elif day in LAST3:
            tag = " [LAST3]"
        if tag or day.startswith("2026-09") or day.startswith("2026-10"):
            print(
                day + tag,
                "pnl",
                d.get("pnl"),
                "trades",
                d.get("trades") or d.get("count"),
            )
except Exception as e:
    print("calendar_err", e)

print("\n=== BRIDGE STATUS ===")
try:
    st = bridge_get("/api/status")
    acct = st.get("account") or {}
    print(
        "connected",
        st.get("connected"),
        "mode",
        st.get("mode") or acct.get("server"),
        "bal",
        acct.get("balance"),
        "profit",
        acct.get("profit"),
    )
except Exception as e:
    print("status_err", e)

print("\n=== INCOME VIA LIVE KEYS ===")
key, secret, testnet = live_keys()
base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
print("base", base, "key_len", len(key))
start = int(datetime(2026, 9, 23, tzinfo=timezone.utc).timestamp() * 1000)
end = int(now.timestamp() * 1000) + 1000
rows = pull_income(base, key, secret, "REALIZED_PNL", start, end) if key and secret else []
print("INCOME_ROWS", len(rows))

# If env keys 401, ask connector object via a one-shot import of persisted encrypted session
if not rows:
    print("trying connector.cfg from session restore helpers…")
    try:
        from binance_connector import BinanceConnector, BinanceConfig

        # Mimic main startup: load stored session if helper exists
        cfg = BinanceConfig()
        for mod_name in ("session_crypto", "binance_session", "secure_store"):
            try:
                mod = __import__(mod_name)
            except Exception:
                continue
            for fn in ("load_session", "restore_session", "read_session", "load"):
                if hasattr(mod, fn):
                    try:
                        sess = getattr(mod, fn)()
                        print("tried", mod_name, fn, type(sess), list(sess)[:8] if isinstance(sess, dict) else "")
                    except Exception as e:
                        print("fail", mod_name, fn, e)
        # Read from trade history cache as fallback PnL source
    except Exception as e:
        print("connector_try", e)

cache = Path("/var/lib/bilshenz/trade-history-cache.json")
print("\n=== TRADE HISTORY CACHE ===")
if cache.exists():
    try:
        cj = json.loads(cache.read_text() or "{}")
        deals = cj.get("deals") or cj.get("rows") or []
        print("cache_deals", len(deals), "keys", list(cj.keys())[:12])
        by_win = defaultdict(float)
        by_win_n = defaultdict(int)
        by_day = defaultdict(float)
        by_sym = defaultdict(lambda: defaultdict(float))
        fills = []
        for d in deals:
            if not isinstance(d, dict):
                continue
            if d.get("is_close") is False:
                continue
            pnl = d.get("profit")
            if pnl is None:
                pnl = d.get("realized_pnl")
            try:
                pnl = float(pnl or 0)
            except Exception:
                continue
            t = int(d.get("time") or 0)
            if t <= 0:
                continue
            # ms or s
            if t < 10_000_000_000:
                t *= 1000
            day = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")
            sym = str(d.get("symbol") or "")
            by_day[day] += pnl
            w = bucket(day)
            if not w:
                continue
            by_win[w] += pnl
            by_win_n[w] += 1
            by_sym[w][sym] += pnl
            fills.append((w, day, sym, pnl, t))
        print("DAILY from cache (close fills):")
        for day in sorted(by_day):
            tag = " [BASE]" if day in BASE_DAYS else (" [LAST3]" if day in LAST3 else "")
            print(f"  {day}{tag} pnl={round(by_day[day], 2)}")
        for w in ("SEP23_25", "LAST3"):
            wins = [x for x in fills if x[0] == w and x[3] > 0]
            losses = [x for x in fills if x[0] == w and x[3] < 0]
            print(
                w,
                "n",
                by_win_n[w],
                "pnl",
                round(by_win[w], 2),
                "sum_wins",
                round(sum(x[3] for x in wins), 2),
                "sum_losses",
                round(sum(x[3] for x in losses), 2),
            )
            print("  worst8:")
            for row in sorted([x for x in fills if x[0] == w], key=lambda x: x[3])[:8]:
                print("   ", row[1], row[2], round(row[3], 2))
            print("  sym worst8:")
            for s, v in sorted(by_sym[w].items(), key=lambda kv: kv[1])[:8]:
                print("   ", s, round(v, 2))
    except Exception as e:
        print("cache_err", e)
else:
    print("no cache")

# Stream logs line-by-line (avoid OOM)
print("\n=== LOG EXIT REASONS (stream) ===")
re_close = re.compile(r"scanner closed ([A-Z0-9]+) reason=([A-Z0-9_]+)")
re_leg = re.compile(r"closed leg ([A-Z0-9]+) (long1|long2|short) reason=([A-Z0-9_]+)")
re_inval = re.compile(r"INVALIDATION adverse=([0-9.]+)")
re_solo = re.compile(r"(LONG1_PULLBACK|LONG2_PULLBACK|LONG1_TP|LONG2_TP)")
re_4131 = re.compile(r"(-4131|PERCENT_PRICE|force_flat_4131|PARTIAL_CLOSE|stuck_close)")
re_short = re.compile(r"scanner SHORT ([A-Z0-9]+) qty=([0-9.]+) @ ([0-9.]+)")
re_l1 = re.compile(r"scanner LONG1 ([A-Z0-9]+) qty=([0-9.]+) @ ([0-9.]+)")
re_l2 = re.compile(r"scanner LONG2 ([A-Z0-9]+) qty=([0-9.]+) @ ([0-9.]+)")
re_manual = re.compile(
    r"EXEC_OK coin=([A-Z0-9]+) side=(\w+) qty=([0-9.]+) fill=([0-9.]+).*manual=True"
)
re_fail = re.compile(r"scanner SHORT failed ([A-Z0-9]+): (.+)$")
re_hedge_ep = re.compile(r"(solo_hedge|hedge_episode|_solo_hedge_exit|_hedge_episode_active|PAIRED|paired hold)")

pair_c = defaultdict(Counter)
leg_c = defaultdict(Counter)
inval = defaultdict(list)
solo = defaultdict(Counter)
e4131 = defaultdict(int)
shorts = defaultdict(list)
l1n = defaultdict(int)
l2n = defaultdict(int)
manuals = defaultdict(list)
fails = defaultdict(Counter)

LOG_DIR = Path("/var/log/bilshenz")


def handle_line(ln: str):
    if len(ln) < 10:
        return
    day = ln[:10]
    w = bucket(day)
    if not w:
        return
    m = re_close.search(ln)
    if m:
        pair_c[w][m.group(2)] += 1
    m = re_leg.search(ln)
    if m:
        leg_c[w][f"{m.group(2)}:{m.group(3)}"] += 1
    m = re_inval.search(ln)
    if m:
        inval[w].append(float(m.group(1)))
    m = re_solo.search(ln)
    if m:
        solo[w][m.group(1)] += 1
    if re_4131.search(ln):
        e4131[w] += 1
    m = re_short.search(ln)
    if m:
        qty = float(m.group(2))
        px = float(m.group(3))
        shorts[w].append((day, m.group(1), qty * px))
    if re_l1.search(ln):
        l1n[w] += 1
    if re_l2.search(ln):
        l2n[w] += 1
    m = re_manual.search(ln)
    if m:
        qty = float(m.group(3))
        px = float(m.group(4))
        manuals[w].append((day, m.group(1), m.group(2), qty * px))
    m = re_fail.search(ln)
    if m:
        fails[w][m.group(2)[:50]] += 1


for name in sorted(LOG_DIR.glob("binance-api.log*")):
    try:
        if str(name).endswith(".gz"):
            f = gzip.open(name, "rt", errors="replace")
        else:
            f = open(name, "r", errors="replace")
        with f:
            for ln in f:
                handle_line(ln)
        print("LOG_OK", name.name)
    except Exception as e:
        print("LOG_FAIL", name.name, e)

for w in ("SEP23_25", "LAST3"):
    print("PAIR_CLOSE", w, dict(pair_c[w].most_common(15)), "TOTAL", sum(pair_c[w].values()))
    print("LEG_CLOSE", w, dict(leg_c[w].most_common(15)), "TOTAL", sum(leg_c[w].values()))
    xs = inval[w]
    print(
        "INVALIDATION",
        w,
        "n",
        len(xs),
        "avg",
        round(sum(xs) / len(xs), 2) if xs else 0,
        "max",
        max(xs) if xs else 0,
    )
    print("SOLO_HEDGE_MARKERS", w, dict(solo[w]))
    print("4131_MARKERS", w, e4131[w])
    print("OPENS", w, "shorts", len(shorts[w]), "l1", l1n[w], "l2", l2n[w], "manuals", len(manuals[w]))
    if shorts[w]:
        ns = [x[2] for x in shorts[w]]
        print(
            "  short_notional avg",
            round(sum(ns) / len(ns), 2),
            "max",
            round(max(ns), 2),
            "min",
            round(min(ns), 2),
        )
    if manuals[w]:
        print("  manual top:")
        for row in sorted(manuals[w], key=lambda x: -x[3])[:8]:
            print("   ", row[0], row[1], row[2], "notional", round(row[3], 2))
    if fails[w]:
        print("  short_fails", dict(fails[w].most_common(5)))

# Income rows if we got them
if rows:
    by_win = defaultdict(float)
    by_win_n = defaultdict(int)
    by_day = defaultdict(float)
    by_sym = defaultdict(lambda: defaultdict(float))
    fills = []
    for r in rows:
        try:
            pnl = float(r.get("income") or 0)
        except Exception:
            continue
        t = int(r.get("time") or 0)
        day = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")
        sym = str(r.get("symbol") or "")
        by_day[day] += pnl
        w = bucket(day)
        if not w:
            continue
        by_win[w] += pnl
        by_win_n[w] += 1
        by_sym[w][sym] += pnl
        fills.append((w, day, sym, pnl, t))
    print("\n=== BINANCE REALIZED ===")
    for day in sorted(by_day):
        tag = " [BASE]" if day in BASE_DAYS else (" [LAST3]" if day in LAST3 else "")
        print(f"{day}{tag} pnl={round(by_day[day], 2)}")
    for w in ("SEP23_25", "LAST3"):
        print(w, "n", by_win_n[w], "pnl", round(by_win[w], 2))
        print("  sym worst:")
        for s, v in sorted(by_sym[w].items(), key=lambda kv: kv[1])[:10]:
            print("   ", s, round(v, 2))

print("\nDONE")
