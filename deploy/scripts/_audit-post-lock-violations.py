#!/usr/bin/env python3
"""Audit FRA trades AFTER violation-lock deploy for remaining rule breaks."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import re, json, urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from dataclasses import dataclass, field

# Deploy commit landed ~2026-10-03; use service restart / first LOCK marker if present.
CUTOFF = "2026-10-03T12:00:00"  # local FRA clock after push/deploy day

text = ""
for p in (Path("/var/log/bilshenz/binance-api.log"), Path("/var/log/bilshenz/binance-api.log.1")):
    if p.exists():
        text += p.read_text(errors="replace") + "\n"

# Find when violation locks actually went live (restart after deploy)
restart_ts = []
for m in re.finditer(r"(20\d\d-\d\d-\d\dT\S+).*?(VIOLATION_LOCKS_DEPLOYED|FULL_DEPLOY_OK|scanner risk sanitized)", text):
    restart_ts.append(m.group(1))
print("MARKERS", restart_ts[-8:])

# Also use journalctl-ish from log: first test_violation / paired hold after hedge in process
# Practical cutoff: after last FULL deploy of Oct 3 if present else CUTOFF
cutoff = CUTOFF
for m in re.finditer(r"(20\d\d-\d\d-\d\dT\S+).*FULL_DEPLOY_OK", text):
    cutoff = m.group(1)
for m in re.finditer(r"(20\d\d-\d\d-\d\dT\S+).*VIOLATION_LOCKS_DEPLOYED", text):
    cutoff = m.group(1)
# Prefer earliest Oct 3 afternoon restart of api
api_starts = re.findall(r"(20\d\d-\d\d-\d\dT\S+) INFO \[main\] .*started|Listening|Uvicorn running", text)
print("API_START_SAMPLES", api_starts[-5:] if api_starts else None)
print("USING_CUTOFF", cutoff)

P_SHORT = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)")
P_L1 = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG1 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)")
P_L2 = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG2 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)")
P_ADOPT_S = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner adopted exchange SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)")
P_CLOSE_LEG = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed leg (?P<sym>\S+) (?P<leg>\S+) reason=(?P<reason>\S+)")
P_CLOSE = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed (?P<sym>\S+) reason=(?P<reason>\S+)")
P_PB = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) (?P<kind>LONG1_PULLBACK|LONG2_PULLBACK|SHORT_PULLBACK) (?P<pct>[\d.]+)%")
P_INV = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) INVALIDATION adverse=(?P<adv>[\d.]+)")
P_FAIL = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) WARNING \[momentum_scanner\] scanner (?P<leg>SHORT|LONG1|LONG2) failed (?P<sym>\S+): (?P<err>.+?)(?:\s+latency|$)")
P_LEV = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[binance_connector\] exchange leverage (?P<sym>\S+) set (?P<fr>\d+)x -> (?P<to>\d+)x")
P_PAIR = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) paired hold blocks solo (?P<reason>\S+)")
P_MANUAL_REJ = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+).*manual_qty_exceeds_locked_partition")
P_EXEC = re.compile(r"(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[execution_engine\] EXEC_OK coin=(?P<sym>\S+) side=(?P<side>\S+) qty=(?P<qty>[\d.]+) fill=(?P<fill>[\d.eE+-]+).*manual=(?P<manual>True|False)")

events = []
for rx, kind in [
    (P_SHORT, "SHORT"), (P_L1, "LONG1"), (P_L2, "LONG2"), (P_ADOPT_S, "ADOPT_SHORT"),
    (P_CLOSE_LEG, "CLOSE_LEG"), (P_CLOSE, "CLOSE"), (P_PB, "PULLBACK"), (P_INV, "INVALIDATION"),
    (P_FAIL, "FAIL"), (P_LEV, "LEV"), (P_PAIR, "PAIR_BLOCK"), (P_MANUAL_REJ, "MANUAL_REJ"),
    (P_EXEC, "EXEC"),
]:
    for m in rx.finditer(text):
        d = m.groupdict(); d["kind"] = kind
        if d["ts"] >= cutoff:
            events.append(d)
events.sort(key=lambda d: d["ts"])
print("POST_EVENTS", len(events), "from", events[0]["ts"] if events else "-", "to", events[-1]["ts"] if events else "-")

@dataclass
class Trade:
    sym: str
    short_ts: str = ""
    short_px: float = 0.0
    short_qty: float = 0.0
    adopted: bool = False
    l1_ts: str = ""; l1_px: float = 0.0
    l2_ts: str = ""; l2_px: float = 0.0
    l1_closed: str = ""; l2_closed: str = ""
    end: str = ""; end_ts: str = ""
    fails: list = field(default_factory=list)
    lev: list = field(default_factory=list)
    pbs: list = field(default_factory=list)
    pair_blocks: list = field(default_factory=list)
    viol: list = field(default_factory=list)
    notes: list = field(default_factory=list)

open_t = {}; done = []

def fin(sym, reason, ts):
    t = open_t.pop(sym, None)
    if t:
        t.end = reason; t.end_ts = ts; done.append(t)

for e in events:
    k = e["kind"]; sym = e.get("sym", "")
    if k in ("SHORT", "ADOPT_SHORT"):
        if sym in open_t:
            open_t[sym].viol.append("OVERLAPPING_SHORT_WITHOUT_CLOSE")
            fin(sym, "IMPLIED_REPLACE", e["ts"])
        open_t[sym] = Trade(sym=sym, short_ts=e["ts"], short_px=float(e["px"]), short_qty=float(e["qty"]), adopted=k == "ADOPT_SHORT")
    elif k == "LONG1":
        t = open_t.get(sym)
        if not t:
            t = Trade(sym=sym); t.viol.append("LONG1_WITHOUT_TRACKED_SHORT"); open_t[sym] = t
        t.l1_ts = e["ts"]; t.l1_px = float(e["px"])
        if t.short_px > 0:
            adv = (t.l1_px - t.short_px) / t.short_px * 100
            t.notes.append(f"l1_adv={adv:.2f}")
            if adv < 1.8: t.viol.append(f"LONG1_EARLY_{adv:.2f}")
            if adv >= 6.5: t.viol.append(f"LONG1_PAST_INVALIDATION_{adv:.2f}")
    elif k == "LONG2":
        t = open_t.get(sym)
        if not t:
            t = Trade(sym=sym); t.viol.append("LONG2_WITHOUT_TRACKED_SHORT"); open_t[sym] = t
        t.l2_ts = e["ts"]; t.l2_px = float(e["px"])
        if t.short_px > 0:
            adv = (t.l2_px - t.short_px) / t.short_px * 100
            t.notes.append(f"l2_adv={adv:.2f}")
            if adv < 3.8: t.viol.append(f"LONG2_EARLY_{adv:.2f}")
            if adv >= 6.5: t.viol.append(f"LONG2_PAST_INVALIDATION_{adv:.2f}")
    elif k == "CLOSE_LEG":
        t = open_t.get(sym)
        if t:
            if e["leg"] == "LONG1": t.l1_closed = e["reason"]
            if e["leg"] == "LONG2": t.l2_closed = e["reason"]
            if e["leg"] == "SHORT": fin(sym, e["reason"], e["ts"])
    elif k == "CLOSE":
        fin(sym, e["reason"], e["ts"])
    elif k == "INVALIDATION":
        t = open_t.get(sym)
        if t:
            t.notes.append(f"inv={e['adv']}")
            if t.l1_closed and "PULLBACK" in t.l1_closed.upper():
                t.viol.append("HEDGE_EXIT_THEN_INVALIDATION")
            if not t.l1_ts and not t.l2_ts:
                t.viol.append("INVALIDATION_WITH_NO_HEDGES")
        fin(sym, "INVALIDATION", e["ts"])
    elif k == "FAIL":
        t = open_t.get(sym)
        if t: t.fails.append((e["leg"], e["err"][:120]))
    elif k == "LEV":
        t = open_t.get(sym)
        if t:
            t.lev.append((e["fr"], e["to"], e["ts"]))
            # naked force 5->10 while no L1 yet
            if e["fr"] == "5" and e["to"] == "10" and not t.l1_ts:
                t.viol.append("NAKED_SHORT_LEVERAGE_5_TO_10")
    elif k == "PULLBACK":
        t = open_t.get(sym)
        if t: t.pbs.append((e["kind"], e["pct"]))
    elif k == "PAIR_BLOCK":
        t = open_t.get(sym)
        if t: t.pair_blocks.append(e["reason"])
    elif k == "EXEC" and e.get("manual") == "True":
        # size check roughly: notional proxy qty*fill
        try:
            notional = float(e["qty"]) * float(e["fill"])
            # short max ~50@$100@5x = 250 notional; long max ~40@$100@10x = 400
            if e["side"] == "SELL" and notional > 280:
                print("MANUAL_OVERSIZE_SELL", e["ts"], e["sym"], f"notional={notional:.1f}")
            if e["side"] == "BUY" and notional > 450:
                print("MANUAL_OVERSIZE_BUY", e["ts"], e["sym"], f"notional={notional:.1f}")
        except Exception:
            pass

for sym, t in list(open_t.items()):
    t.end = "OPEN"; done.append(t)

# leverage held at 10 with no hedges ever
for t in done:
    if any(to == "10" for fr, to, ts in t.lev) and not t.l1_ts and not t.l2_ts:
        if "NAKED_SHORT_HELD_AT_10X" not in t.viol:
            t.viol.append("NAKED_SHORT_HELD_AT_10X")
    # short size outlier vs $100@5x (~$250 notional, margin ~$50)
    if t.short_px and t.short_qty:
        notional = t.short_qty * t.short_px
        margin5 = notional / 5
        if margin5 > 80:  # well above 50% of $100
            t.viol.append(f"SHORT_SIZE_OUTLIER_margin5={margin5:.1f}")

ctr = Counter()
print("\n=== POST-LOCK TRADES ===")
for t in done:
    for v in t.viol:
        ctr[v.split("_")[0] + "_" + "_".join(v.split("_")[1:3])]  # noop keep full
        ctr[v] += 1
    print(f"{t.sym} short@{t.short_px} ts={t.short_ts[11:19]} adopt={t.adopted}")
    print(f"  L1={t.l1_ts[11:19] if t.l1_ts else '-'}@{t.l1_px or '-'} closed={t.l1_closed or '-'} | L2={t.l2_ts[11:19] if t.l2_ts else '-'}@{t.l2_px or '-'} closed={t.l2_closed or '-'}")
    print(f"  END {t.end} @{t.end_ts[11:19] if t.end_ts else '-'} fails={t.fails} lev={t.lev} pair_blocks={t.pair_blocks}")
    print(f"  notes={t.notes}")
    print(f"  VIOLATIONS: {'; '.join(t.viol) if t.viol else 'none'}")

print("\n=== POST-LOCK VIOLATION COUNTS ===")
for v, n in ctr.most_common():
    print(f"  {n}  {v}")
print("trades", len(done), "with_viol", sum(1 for t in done if t.viol))

# live snapshot
tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
req = urllib.request.Request("http://127.0.0.1:8766/api/status", headers={"Authorization": "Bearer " + tok})
st = json.loads(urllib.request.urlopen(req, timeout=12).read())
sc = h.get("scanner") or {}
print("\n=== LIVE ===")
print("mode", h.get("mode"), "conn", h.get("connected"), "can", sc.get("can_execute"), "part", sc.get("partition_usd"), "active", sc.get("active_symbol"))
print("testnet", st.get("testnet"), "balance", (st.get("account") or {}).get("balance"))
pos = st.get("positions") or st.get("open_positions") or []
if isinstance(pos, dict):
    pos = pos.get("items") or pos.get("positions") or list(pos.values())
print("positions_raw_type", type(pos).__name__, "count", len(pos) if hasattr(pos, "__len__") else "?")
for p in (pos if isinstance(pos, list) else [])[:12]:
    if isinstance(p, dict):
        print(" POS", p.get("symbol") or p.get("coin"), "side", p.get("side") or p.get("positionSide"), "qty", p.get("qty") or p.get("quantity") or p.get("positionAmt"), "entry", p.get("entry") or p.get("entryPrice"), "lev", p.get("leverage"))

# recent fails post cutoff
fails = [e for e in events if e["kind"] == "FAIL"]
print("\n=== POST-LOCK FAILS ===")
for e in fails[-20:]:
    print(e["ts"][11:19], e["leg"], e["sym"], e["err"][:140])

# paired hold evidence
pairs = [e for e in events if e["kind"] == "PAIR_BLOCK"]
print("PAIR_BLOCKS", len(pairs))
for e in pairs[-10:]:
    print(e["ts"][11:19], e["sym"], e["reason"])

print("AUDIT_POST_LOCK_DONE")
PY
'''

_, o, e = c.exec_command(CMD, timeout=120)
out = o.read().decode("utf-8", "replace")
err = e.read().decode("utf-8", "replace")
print(out.encode("ascii", "replace").decode("ascii"))
if err.strip():
    print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
Path(__file__).with_name("_post-lock-violations.txt").write_text(out, encoding="utf-8")
c.close()
