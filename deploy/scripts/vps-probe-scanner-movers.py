#!/usr/bin/env python3
"""Read-only: current scanner movers + cool miss summary (no secrets)."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
TOKEN=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 - <<'PY'
import json
from collections import Counter
d=json.load(open('/tmp/snap.json'))
rows=d.get('rows') or []
print('keys_sample', sorted((rows[0] or {}).keys())[:40] if rows else None)
def num(r,*ks):
  for k in ks:
    try:
      v=float(r.get(k)); 
      if v==v: return v
    except Exception: pass
  return None
# print a few raw watching
for r in rows[:3]:
  print('SAMPLE', {k:r.get(k) for k in list(r)[:25]})
vals=[]
for r in rows:
  g = num(r,'pct15','change15m','change_15m','gainPct','gain_pct','bestPct','best_pct','qualifyingPct','qualifying_pct')
  vals.append((g if g is not None else -999, r))
vals.sort(key=lambda x: x[0], reverse=True)
print('status', dict(Counter(str(r.get('status')) for r in rows)))
print('TOP12_by_pct15_or_gain')
for g,r in vals[:12]:
  print(r.get('symbol'), 'st', r.get('status'), 'g', g, 'retrace', r.get('retracePct') or r.get('retrace_pct'), 'best', r.get('bestPct') or r.get('best_pct'), 'live', r.get('livePct') or r.get('live_pct') or r.get('pct15'))
hot=[(g,r) for g,r in vals if g is not None and g>=5]
near=[(g,r) for g,r in vals if g is not None and 3<=g<5]
print('ge5', len(hot), [r.get('symbol') for g,r in hot])
print('3to5', len(near), [(r.get('symbol'), round(g,2)) for g,r in near])
print('watching_detail')
for r in rows:
  if str(r.get('status'))=='Watching':
    print(r.get('symbol'), {k:r.get(k) for k in ('pct15','gainPct','bestPct','retracePct','livePct','qualifyingPct','status') if k in r or True})
PY
echo '=== SHORT OPENS TODAY ==='
grep 'scanner SHORT ' /var/log/bilshenz/binance-api.log | grep 'qty=' | grep '2026-09-29' | tail -n 20
echo '=== SHORT FAILS TODAY (unique coins) ==='
grep 'scanner SHORT failed' /var/log/bilshenz/binance-api.log | grep '2026-09-29' | sed 's/.*failed //' | cut -d: -f1 | sort | uniq -c | sort -rn | head
echo '=== COOL vs OTHER FAIL ==='
grep 'EXEC_FAIL' /var/log/bilshenz/binance-api.log | grep '2026-09-29' | grep -c cooling || true
grep 'EXEC_FAIL' /var/log/bilshenz/binance-api.log | grep '2026-09-29' | grep -cv cooling || true
echo '=== MODE ==='
curl -sS --max-time 8 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c 'import sys,json;d=json.load(sys.stdin);s=d.get("scanner") or {};print("mode",d.get("mode"),"exec",s.get("can_execute"),"block",s.get("exec_block"),"partition",s.get("partition_usd"),"err",s.get("last_exec_error"),"strategy",s.get("strategy_id") or s.get("strategy"))'
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=90)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-500:])
    c.close()
if __name__=='__main__':
    main()
