#!/usr/bin/env python3
"""Deep forensic: Oct 9–10 closed PnL / sides / reasons vs Sep 23–28 baseline."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
REMOTE_PY = r"""
export PYTHONIOENCODING=utf-8
/opt/bilshenz/binance_trading_system/python/.venv/bin/python - <<'PY'
import json, re, time
from collections import Counter, defaultdict
from pathlib import Path

raw = json.loads(Path("/var/lib/bilshenz/trade-history-cache.json").read_text(encoding="utf-8"))
deals = raw.get("deals") or []
cal = raw.get("calendar") or {}
log_paths = [
    Path("/var/log/bilshenz/scanner.log"),
    Path("/var/log/bilshenz/bridge.log"),
    Path("/opt/bilshenz/logs/scanner.log"),
    Path("/opt/bilshenz/var/log/scanner.log"),
]

def ts(d):
    v = d.get("time") or d.get("closeTime") or 0
    x = float(v or 0)
    return int(x if x > 1e12 else x * 1000)

def day_key(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))

def pnl(d):
    return float(d.get("realized_pnl") or d.get("profit") or 0)

print("=== FULL CAL DAYS Sep23+ / Oct ===")
days = cal.get("days") or cal
if isinstance(days, list):
    for row in days:
        dk = str(row.get("date") or row.get("day") or "")
        if (dk.startswith("2026-09") and dk >= "2026-09-23") or dk.startswith("2026-10"):
            print("CAL", dk, "pnl", round(float(row.get("pnl") or row.get("profit") or 0), 2),
                  "n", row.get("n") or row.get("trades") or row.get("fills"))
elif isinstance(days, dict):
    for dk in sorted(days):
        if (dk.startswith("2026-09") and dk >= "2026-09-23") or dk.startswith("2026-10"):
            print("CAL", dk, days[dk])

# deal field sample
for d in deals:
    if d.get("is_close") and day_key(ts(d)) >= "2026-10-09":
        print("SAMPLE_KEYS", sorted(d.keys()))
        print("SAMPLE", json.dumps({k: d.get(k) for k in sorted(d.keys())}, default=str)[:1200])
        break

focus = {"2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28",
         "2026-10-09", "2026-10-10"}

by_day = defaultdict(lambda: {"closes": 0, "pnl": 0.0, "short": [0, 0.0], "long": [0, 0.0], "other": [0, 0.0]})
for d in deals:
    if not d.get("is_close"):
        continue
    dk = day_key(ts(d))
    if dk not in focus and not (dk.startswith("2026-10") and dk >= "2026-10-01"):
        continue
    slot = by_day[dk]
    slot["closes"] += 1
    p = pnl(d)
    slot["pnl"] += p
    side = str(d.get("positionSide") or d.get("position_side") or "").upper()
    if side in ("SHORT", "SELL"):
        slot["short"][0] += 1
        slot["short"][1] += p
    elif side in ("LONG", "BUY"):
        slot["long"][0] += 1
        slot["long"][1] += p
    else:
        # infer from side field
        s2 = str(d.get("side") or "").upper()
        if s2 == "BUY":  # closing short
            slot["short"][0] += 1
            slot["short"][1] += p
        elif s2 == "SELL":  # closing long
            slot["long"][0] += 1
            slot["long"][1] += p
        else:
            slot["other"][0] += 1
            slot["other"][1] += p

print("=== DEAL CLOSED PnL BY DAY (Sep focus + Oct) ===")
for dk in sorted(by_day):
    s = by_day[dk]
    print(f"DAY {dk} closes={s['closes']} pnl={round(s['pnl'],2)} "
          f"SHORT n={s['short'][0]} pnl={round(s['short'][1],2)} "
          f"LONG n={s['long'][0]} pnl={round(s['long'][1],2)} "
          f"OTHER n={s['other'][0]} pnl={round(s['other'][1],2)}")

print("=== BIG CLOSES |pnl|>=5 Oct9-10 ===")
big = [d for d in deals if d.get("is_close") and day_key(ts(d)) in ("2026-10-09", "2026-10-10") and abs(pnl(d)) >= 5]
for d in sorted(big, key=lambda x: -abs(pnl(x))):
    print(day_key(ts(d)), time.strftime("%H:%M:%S", time.gmtime(ts(d) / 1000)),
          d.get("symbol"),
          "pos", d.get("positionSide") or d.get("position_side"),
          "side", d.get("side"),
          "qty", d.get("qty") or d.get("volume") or d.get("quantity") or d.get("closed_qty"),
          "pnl", round(pnl(d), 2),
          "lev", d.get("leverage"),
          "entry", d.get("entryPrice") or d.get("entry_price") or d.get("entry"),
          "price", d.get("price") or d.get("avgPrice") or d.get("exitPrice"),
          "reason", d.get("reason") or d.get("close_reason") or d.get("exit_reason") or d.get("comment") or d.get("note"))

# Parse scanner log for close reasons Oct9-10
print("=== LOG CLOSE REASONS Oct9-10 ===")
pat = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*?(?:CLOSE|close|RESCUE|SHORT_TP|LONG1|LONG2|INVALID|SMART_EXIT|PULLBACK).*?(?P<sym>[A-Z0-9]+USDT).*?(?P<reason>SHORT_TP|LONG1_TP|LONG2_TP|RESCUE|SMART_EXIT|PULLBACK|INVALIDATION|SHORT_GONE|MANUAL|TP|SL)?"
)
# simpler line scrape
close_re = re.compile(
    r"(?P<ts>2026-10-0[9]|2026-10-10T[0-9:]+).*?(?:scanner close|CLOSE_OK|closed|exit).*",
    re.I,
)
reason_counts = Counter()
reason_by_day = defaultdict(Counter)
samples = []
log_found = None
for lp in [
    Path("/var/log/bilshenz/momentum_scanner.log"),
    Path("/var/log/bilshenz/app.log"),
    Path("/opt/bilshenz/logs/app.log"),
    Path("/opt/bilshenz/var/log/app.log"),
]:
    if lp.exists():
        log_found = lp
        break
# glob
if not log_found:
    for p in Path("/var/log/bilshenz").glob("*.log") if Path("/var/log/bilshenz").exists() else []:
        log_found = p
        break
    for p in Path("/opt/bilshenz").rglob("*.log"):
        if "scanner" in p.name.lower() or "momentum" in p.name.lower() or p.name == "app.log":
            log_found = p
            break

print("LOG_FILE", log_found)
if log_found:
    text = log_found.read_text(encoding="utf-8", errors="replace")
    # also try journal-style rotated
else:
    text = ""
    # try combined from common path used by prior audit
    for cand in Path("/opt/bilshenz").rglob("*scanner*.log"):
        text += cand.read_text(encoding="utf-8", errors="replace")[-5_000_000:]
        print("ALSO", cand)
        break

# Prior audit read LOG_LINES from somewhere — find same source
from glob import glob
cands = []
for g in ["/var/log/bilshenz/*", "/opt/bilshenz/logs/*", "/opt/bilshenz/var/log/*", "/tmp/bilshenz*"]:
    cands.extend(glob(g))
print("LOG_CANDS", cands[:30])

# Read journalctl if needed — use file that audit used
# Replicate audit: it counted LOG_LINES 11537 — find that file in audit script
PY
"""

# Fix: put full remote script without broken nesting — write remote file via sftp
REMOTE_BODY = r'''
import json, re, time
from collections import Counter, defaultdict
from pathlib import Path
from glob import glob

raw = json.loads(Path("/var/lib/bilshenz/trade-history-cache.json").read_text(encoding="utf-8"))
deals = raw.get("deals") or []
cal = raw.get("calendar") or {}

def ts(d):
    v = d.get("time") or d.get("closeTime") or 0
    x = float(v or 0)
    return int(x if x > 1e12 else x * 1000)

def day_key(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))

def pnl(d):
    return float(d.get("realized_pnl") or d.get("profit") or 0)

print("=== FULL CAL DAYS Sep23+ / Oct ===")
days = cal.get("days") or cal
if isinstance(days, list):
    for row in days:
        dk = str(row.get("date") or row.get("day") or "")
        if (dk.startswith("2026-09") and dk >= "2026-09-23") or dk.startswith("2026-10"):
            print("CAL", dk, "pnl", round(float(row.get("pnl") or row.get("profit") or 0), 2),
                  "n", row.get("n") or row.get("trades") or row.get("fills"))
elif isinstance(days, dict):
    for dk in sorted(days):
        if (dk.startswith("2026-09") and dk >= "2026-09-23") or dk.startswith("2026-10"):
            print("CAL", dk, days[dk])

for d in deals:
    if d.get("is_close") and day_key(ts(d)) >= "2026-10-09":
        print("SAMPLE_KEYS", sorted(d.keys()))
        print("SAMPLE", json.dumps({k: d.get(k) for k in sorted(d.keys())}, default=str)[:1500])
        break

focus_days = [dk for dk in sorted({day_key(ts(d)) for d in deals if ts(d)}) if (dk >= "2026-09-23" and dk.startswith("2026-09")) or dk.startswith("2026-10")]
by_day = defaultdict(lambda: {"closes": 0, "pnl": 0.0, "short": [0, 0.0], "long": [0, 0.0], "other": [0, 0.0]})
for d in deals:
    if not d.get("is_close"):
        continue
    dk = day_key(ts(d))
    if dk not in focus_days:
        continue
    slot = by_day[dk]
    slot["closes"] += 1
    p = pnl(d)
    slot["pnl"] += p
    side = str(d.get("positionSide") or d.get("position_side") or "").upper()
    s2 = str(d.get("side") or "").upper()
    if side in ("SHORT", "SELL") or (not side and s2 == "BUY"):
        slot["short"][0] += 1
        slot["short"][1] += p
    elif side in ("LONG", "BUY") or (not side and s2 == "SELL"):
        slot["long"][0] += 1
        slot["long"][1] += p
    else:
        slot["other"][0] += 1
        slot["other"][1] += p

print("=== DEAL CLOSED PnL BY DAY ===")
for dk in sorted(by_day):
    s = by_day[dk]
    print(f"DAY {dk} closes={s['closes']} pnl={round(s['pnl'],2)} SHORT n={s['short'][0]} pnl={round(s['short'][1],2)} LONG n={s['long'][0]} pnl={round(s['long'][1],2)} OTHER n={s['other'][0]} pnl={round(s['other'][1],2)}")

print("=== BIG CLOSES |pnl|>=5 Oct9-10 ===")
big = [d for d in deals if d.get("is_close") and day_key(ts(d)) in ("2026-10-09", "2026-10-10") and abs(pnl(d)) >= 5]
for d in sorted(big, key=lambda x: -abs(pnl(x))):
    print(day_key(ts(d)), time.strftime("%H:%M:%S", time.gmtime(ts(d) / 1000)),
          d.get("symbol"),
          "pos", d.get("positionSide") or d.get("position_side"),
          "side", d.get("side"),
          "qty", d.get("qty") or d.get("volume") or d.get("quantity") or d.get("closed_qty"),
          "pnl", round(pnl(d), 2),
          "lev", d.get("leverage"),
          "entry", d.get("entryPrice") or d.get("entry_price") or d.get("entry"),
          "price", d.get("price") or d.get("avgPrice") or d.get("exitPrice"),
          "notional", round(abs(float(d.get("qty") or d.get("volume") or d.get("quantity") or 0)) * float(d.get("price") or d.get("avgPrice") or d.get("entryPrice") or 0), 2) if (d.get("price") or d.get("avgPrice") or d.get("entryPrice")) else None,
          "reason", d.get("reason") or d.get("close_reason") or d.get("exit_reason") or d.get("comment") or d.get("note"))

# Log close reasons — same path prior audit used
log_text = ""
cands = []
for g in ["/var/log/bilshenz/*", "/opt/bilshenz/logs/*", "/opt/bilshenz/var/log/*"]:
    cands.extend(glob(g))
print("LOG_CANDS", cands[:40])
for p in cands:
    if not p.endswith(".log") and "journal" not in p:
        continue
    try:
        chunk = Path(p).read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if "momentum_scanner" in chunk or "SHORT_TP" in chunk or "RESCUE" in chunk:
        log_text += chunk[-8_000_000:]
        print("USING_LOG", p, "bytes", len(chunk))

# Also journalctl snippet
import subprocess
try:
    j = subprocess.check_output(
        ["journalctl", "-u", "bilshenz", "--since", "2026-10-09", "--no-pager", "-o", "short-iso"],
        stderr=subprocess.DEVNULL, text=True, timeout=60,
    )
    log_text += j[-8_000_000:]
    print("JOURNAL_LEN", len(j))
except Exception as e:
    print("JOURNAL_ERR", e)
    for unit in ["bilshenz", "bilshenz-bridge", "bilshenz-scanner"]:
        try:
            j = subprocess.check_output(
                ["journalctl", "-u", unit, "--since", "2026-10-09", "--no-pager", "-o", "short-iso"],
                stderr=subprocess.DEVNULL, text=True, timeout=60,
            )
            log_text += j[-4_000_000:]
            print("JOURNAL", unit, len(j))
        except Exception as e2:
            print("JOURNAL_ERR", unit, e2)

reason_re = re.compile(
    r"(2026-10-0[9]|2026-10-10)T[0-9:.]+Z?.*?([A-Z0-9]+USDT).*?(SHORT_TP|LONG1_TP|LONG2_TP|RESCUE|SMART_EXIT|PULLBACK|INVALIDATION|SHORT_GONE_EXCHANGE|MANUAL_CLOSE|CLOSE_OK|reason=([A-Z0-9_]+))"
)
# simpler: reason=XXX
simple = re.compile(r"(2026-10-0[9]|2026-10-10)T[^\s]+ .*?([A-Z0-9]+USDT).*?reason=([A-Z0-9_]+)")
close_line = re.compile(r"(2026-10-0[9]|2026-10-10)T[^\s]+ .*?(?:scanner close|CLOSE_|closed).*", re.I)
rc = Counter()
rc_day = defaultdict(Counter)
close_samples = []
for line in log_text.splitlines():
    if "2026-10-09" not in line and "2026-10-10" not in line:
        continue
    m = simple.search(line)
    if m:
        dk, sym, reason = m.group(1)[:10] if False else None, m.group(2), m.group(3)
        # fix day from line
        dm = re.search(r"(2026-10-0[9]|2026-10-10)", line)
        dk = dm.group(1) if dm else "?"
        rc[reason] += 1
        rc_day[dk][reason] += 1
    if any(k in line for k in ("SHORT_TP", "RESCUE", "SMART_EXIT", "PULLBACK", "INVALIDATION", "SHORT_GONE", "LONG1", "LONG2")) and ("close" in line.lower() or "CLOSE" in line or "reason=" in line):
        if len(close_samples) < 40:
            close_samples.append(line[:240])

print("=== REASON= COUNTS Oct9-10 ===")
print(dict(rc))
for dk in sorted(rc_day):
    print(dk, rc_day[dk].most_common(15))
print("=== CLOSE SAMPLE LINES ===")
for s in close_samples[:25]:
    print(s)

# Leverage force markers
print("=== LEV / RULE MARKERS ===")
for key in ["forced 10", "target=10", "exchange_leverage=10", "LONG1 pullback", "solo", "-4005", "SAFE_MODE", "rule_kernel", "SHORT_GONE", "positions unavailable", "min_quote_vol", "liquidity skip", "episode cool"]:
    n = sum(1 for line in log_text.splitlines() if key.lower() in line.lower() and ("2026-10-09" in line or "2026-10-10" in line))
    print(f"HIT {key!r}={n}")
'''


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=25)
    sftp = c.open_sftp()
    remote = "/tmp/_forensic-oct9-10-vs-sep.py"
    with sftp.file(remote, "w") as f:
        f.write(REMOTE_BODY)
    sftp.close()
    _, o, e = c.exec_command(
        "/opt/bilshenz/binance_trading_system/python/.venv/bin/python " + remote,
        timeout=120,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[:3000])
    c.close()


if __name__ == "__main__":
    main()
