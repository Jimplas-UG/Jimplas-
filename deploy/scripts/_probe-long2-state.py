#!/usr/bin/env python3
"""Probe FRA for open legs + Long2 gate state (read-only)."""
from pathlib import Path
import paramiko

pkey = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)

remote = r'''
python3 <<'PY'
import json, urllib.request, subprocess, os, glob

def get(url):
    try:
        return json.load(urllib.request.urlopen(url, timeout=5))
    except Exception as e:
        return {"_err": str(e), "_url": url}

h = get("http://127.0.0.1:8766/health")
print("=== HEALTH ===")
for k in sorted(h.keys()) if isinstance(h, dict) else []:
    v = h.get(k)
    if k in ("positions","open_positions","movers","ticks") or isinstance(v, (list, dict)) and k not in ("strategy","risk","account"):
        if k in ("strategy","risk","account","auth","ws","scanner"):
            print(f"  {k}: {json.dumps(v)[:500]}")
        continue
    print(f"  {k}: {v}")

# dump interesting nested
for k in ("strategy","risk","account","auth","ws","scanner","execution","active"):
    if isinstance(h, dict) and k in h:
        print(f"  NEST {k}: {json.dumps(h[k])[:800]}")

print("=== API POSITIONS ===")
for path in ("/api/positions","/positions","/api/open-positions","/api/status","/api/scanner/status","/api/strategy","/api/health"):
    r = get("http://127.0.0.1:8766" + path)
    if "_err" not in r:
        print(path, json.dumps(r)[:1200])

print("=== DESK API ===")
for path in ("/api/positions","/health","/api/status","/api/trades"):
    r = get("http://127.0.0.1:8791" + path)
    if "_err" not in r:
        print("8791"+path, json.dumps(r)[:1200])

print("=== FIND STATE FILES ===")
out = subprocess.check_output("find /opt/bilshenz /var/lib/bilshenz -maxdepth 5 -type f \\( -name '*session*' -o -name '*coin*' -o -name '*strateg*' -o -name '*persist*' -o -name '*legs*' \\) 2>/dev/null | head -50", shell=True, text=True)
print(out)

print("=== RECENT SERVICE LOGS ===")
# discover unit
units = subprocess.check_output("systemctl list-units --type=service --all 2>/dev/null | grep -iE 'bil|scan|bridge|trad|desk' || true", shell=True, text=True)
print(units)
for u in ("bilshenz","bilshenz-bridge","tradingbot","desk-api","scanner"):
    pass
cmd = "journalctl --no-pager -n 600 2>/dev/null | grep -iE 'LONG2|long2|Long 2|long 2|_long2|adverse|LONG1|long1|hedge|invalidat|orphan|paired|SMART_EXIT|opened|entry blocked|blocked|auth_blocked|signed_ready|EMERGENCY|partition' | tail -100"
print(subprocess.check_output(cmd, shell=True, text=True)[-9000:])

print("=== APP LOG TAIL ===")
logs = subprocess.check_output("ls -lt /opt/bilshenz/logs 2>/dev/null; ls -lt /var/log/*bil* /var/log/*trad* 2>/dev/null | head -20; find /opt/bilshenz -name '*.log' 2>/dev/null | head -20", shell=True, text=True)
print(logs)
PY
'''
_, o, e = c.exec_command(remote, timeout=50)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR:", err[-2500:])
c.close()
