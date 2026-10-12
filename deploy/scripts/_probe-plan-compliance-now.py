#!/usr/bin/env python3
"""Recent closes + open book vs short_first Sep23 plan."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
REMOTE = r'''
import json, time, re
from collections import Counter
from pathlib import Path
import urllib.request

tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}

def get(path):
    req = urllib.request.Request("http://127.0.0.1:8766" + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=25).read())

h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
sc = h.get("scanner") or {}
st = get("/api/status")
pos = get("/api/positions")
acct = st.get("account") or {}
opens = [p for p in (pos.get("positions") or []) if abs(float(p.get("volume") or 0)) > 1e-12]

print("UTC", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
print("PLAN", "short_first_v1", "part", sc.get("partition_usd"), "locked", sc.get("partition_usd_locked") or sc.get("risk_locked"),
      "can", sc.get("can_execute"), "halt", sc.get("user_exec_halted"),
      "bal", acct.get("balance"), "float", acct.get("profit"))
print("ACTIVE", sc.get("active_symbol"), "closed_today", sc.get("trades_closed_today"), "active_n", sc.get("active_strategies"))

# Open compliance
PART = float(sc.get("partition_usd") or 100)
viol = []
by = {}
for p in opens:
    by.setdefault(str(p.get("symbol")).upper(), []).append(p)
for sym, legs in sorted(by.items()):
    shorts = [p for p in legs if str(p.get("positionSide")).upper()=="SHORT" or str(p.get("type")).upper()=="SELL"]
    longs = [p for p in legs if str(p.get("positionSide")).upper()=="LONG" or str(p.get("type")).upper()=="BUY"]
    print("OPEN", sym, "S", len(shorts), "L", len(longs))
    for p in legs:
        qty=float(p.get("volume") or 0); entry=float(p.get("price_open") or p.get("entryPrice") or 0)
        notional=abs(qty)*entry
        print(" ", p.get("positionSide") or p.get("type"), "qty", qty, "entry", entry,
              "ui", p.get("leverage"), "ex", p.get("exchange_leverage"),
              "notional", round(notional,2), "pnl", p.get("profit"))
        side=str(p.get("positionSide") or "").upper()
        lev=float(p.get("exchange_leverage") or p.get("leverage") or 0)
        if side=="SHORT" and not longs and lev>=9.5:
            viol.append((sym,"NAKED_SHORT_10X", lev))
        if side=="SHORT" and notional > PART*0.5*5*1.25+1:
            viol.append((sym,"SHORT_OVERSIZE", notional))
    if longs and not shorts:
        viol.append((sym,"ORPHAN_LONG", len(longs)))
    ln=sum(abs(float(p.get("volume") or 0))*float(p.get("price_open") or 0) for p in longs)
    if ln > PART*0.4*10*2*1.15+1:
        viol.append((sym,"LONG_OVERSIZE", ln))
    # adverse from tick
    if shorts:
        try:
            t=get("/api/tick/"+sym)
            mid=(float(t.get("bid") or 0)+float(t.get("ask") or 0))/2
            entry=float(shorts[0].get("price_open") or 0)
            if entry>0 and mid>0:
                adv=(mid-entry)/entry*100
                print("  adverse%", round(adv,3), "mid", mid)
                if adv>=6.5:
                    viol.append((sym,"PAST_INVALIDATION", adv))
                if longs and adv+1e-9<2.0:
                    # may be OK if entered earlier and price came back — note as soft
                    print("  NOTE longs open while current adverse <2% (paired hold / post-pump pullback — check entry times)")
        except Exception as e:
            print("  tick_err", e)

# Deal cache last 24h
raw=json.loads(Path("/var/lib/bilshenz/trade-history-cache.json").read_text(encoding="utf-8"))
deals=raw.get("deals") or []
cut=int(time.time()*1000)-24*3600*1000
def ts(d):
    v=float(d.get("time") or 0); return int(v if v>1e12 else v*1000)
closes=[d for d in deals if d.get("is_close") and ts(d)>=cut]
pnl=sum(float(d.get("realized_pnl") or d.get("profit") or 0) for d in closes)
print("LAST24H closes", len(closes), "pnl", round(pnl,2))

# Log close reasons + violation markers since midnight UTC Oct11 / last 18h
text=Path("/var/log/bilshenz/app.log").read_text(encoding="utf-8", errors="replace")[-4_000_000:]
reasons=Counter()
bad=Counter()
for line in text.splitlines():
    if "2026-10-10T2" not in line and "2026-10-11" not in line and "2026-10-10T1" not in line:
        if "2026-10-10" not in line and "2026-10-11" not in line:
            continue
    m=re.search(r"scanner closed ([A-Z0-9]+USDT) reason=([A-Z0-9_]+)", line)
    if m:
        reasons[m.group(2)]+=1
    for k in ("SAFE_MODE","rule_kernel","NAKED","target = LONG1","immediate flatten",
              "LONG1_PULLBACK","LONG2_PULLBACK","adopt SHORT refused","defer SHORT_TP",
              "long_residual_abort","SHORT_GONE","paired hold blocks"):
        if k in line or k.lower() in line.lower():
            bad[k]+=1
print("CLOSE_REASONS", dict(reasons))
print("BAD_MARKERS", dict(bad))
print("VIOLATION_N", len(viol))
for v in viol:
    print("VIOLATION", v)

# Recent exec events
ev=sc.get("execution_events") or []
print("RECENT_EXEC")
for e in (ev[:8] if isinstance(ev,list) else []):
    print(" ", e.get("symbol"), e.get("leg"), e.get("side"), e.get("stage"), e.get("quantity"), e.get("fill_price"), e.get("error"))
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", key_filename=str(KEY), timeout=25)
sftp = c.open_sftp()
with sftp.file("/tmp/_probe-plan-compliance-now.py", "w") as f:
    f.write(REMOTE)
sftp.close()
_, o, e = c.exec_command(
    "/opt/bilshenz/binance_trading_system/python/.venv/bin/python /tmp/_probe-plan-compliance-now.py",
    timeout=90,
)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err[:1000])
c.close()
