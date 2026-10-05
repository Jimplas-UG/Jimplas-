#!/usr/bin/env python3
"""Verify each today's hedge adverse % and TP/pullback math vs frozen knobs."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
python3 - <<'PY'
# Manual reconstruction of today's cycles
cycles = [
  # name, short_entry, events: (label, price)
  ("SOON", 0.4276, [("SHORT_TP_close", 0.4146)], None, None),
  ("DEEP", 0.02353, [("LONG1", 0.02401), ("LONG1_close", 0.02426), ("SHORT_close_manual", 0.02344)], None, None),
  ("US_1", 0.02111, [("LONG1", 0.0216), ("LONG1_PB_close", 0.02109), ("SHORT_TP", 0.02056)], None, None),
  ("US_2", 0.02086, [("SHORT_TP", 0.02037)], None, None),
  ("ARK", 0.277, [("LONG1", 0.2831), ("LONG2", 0.2885)], None, None),
  ("MOVR_2", 1.614, [("LONG1", 1.661), ("LONG2", 1.676), ("LONG_close", 1.681), ("SHORT_close_SMART", 1.734)], None, None),
]

GAIN=5.0; RET=0.7; L1=2.0; L2=4.0; STP=2.5; LTP=2.5; INV=6.5; LPB=0.5

print("=== ADVERSE / TP CHECKS vs frozen ===")
for name, short_e, events, *_ in cycles:
    print(f"\n-- {name} short_entry={short_e}")
    for label, px in events:
        if short_e<=0: continue
        if "LONG" in label and "close" not in label.lower() and "PB" not in label:
            adv = (px - short_e)/short_e*100
            need = L1 if "LONG1" in label else L2 if "LONG2" in label else None
            ok = adv + 1e-9 >= need if need else True
            print(f"  {label} @{px} adverse={adv:.3f}% need>={need} OK={ok} {'<< OFF' if not ok else ''}")
        if label.startswith("SHORT_TP") or (label=="SHORT_TP"):
            move = (short_e - px)/short_e*100
            print(f"  {label} @{px} short_profit_move={move:.3f}% need>={STP} OK={move+1e-9>=STP}")
        if "SHORT_close" in label or label.endswith("SMART"):
            move = (short_e - px)/short_e*100
            print(f"  {label} @{px} short_pnl_move={move:.3f}% (neg=loss)")
        if "LONG1" in label and "PB" in label:
            # peak from log US 0.02164, close 0.02095 — pullback from peak
            pass

# LONG notional check: 100*0.4*10 = 400
print("\n=== LONG NOTIONAL (expect ~$400) ===")
for leg, qty, px in [
 ("DEEP L1", 16659.725, 0.02401),
 ("US L1", 18518.518, 0.0216),
 ("ARK L1", 1412.928, 0.2831),
 ("ARK L2", 1386.481, 0.2885),
 ("MOVR L1", 240.818, 1.661),
 ("MOVR L2", 238.663, 1.676),
]:
    n=qty*px
    print(leg, "notional", round(n,2), "err%", round((n-400)/400*100,2))

# SMART_EXIT definition
import momentum_scanner as ms
import inspect
src = open(ms.__file__, encoding='utf-8').read()
print("\n=== SMART_EXIT in scanner? ===")
for i,ln in enumerate(src.splitlines(),1):
    if "SMART_EXIT" in ln or "smart_exit" in ln.lower():
        if "def " in ln or "reason" in ln or "SMART" in ln:
            print(f"{i}: {ln.strip()[:160]}")

# Is SMART_EXIT in frozen contract?
import frozen_strategy as fs
print("frozen mentions SMART", "SMART" in open(fs.__file__,encoding='utf-8').read())
print("EXIT_COST / smart defaults", getattr(ms, "SMART_EXIT_PCT", None), getattr(ms, "EXIT_COST_BUFFER_PCT", None))
PY

# Grep SMART_EXIT context from log around MOVR
grep -n "MOVRUSDT" /var/log/bilshenz/binance-api.log | grep "2026-09-30T07:" | tail -n 40
'''

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=90)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-1000:])
    c.close()
if __name__=='__main__':
    main()
