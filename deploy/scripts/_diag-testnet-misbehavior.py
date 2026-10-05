#!/usr/bin/env python3
"""Deep diagnose FRA testnet trading misbehavior (read-only first pass)."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
set +e
echo '=== SERVICES ==='
systemctl is-active bilshenz-binance-api bilshenz-forward-bot bilshenz-desk-api
ps aux | grep -E 'uvicorn|main:app|forward' | grep -v grep | head -10
echo '=== PORT ==='
ss -lntp | grep -E '8766|8791' || netstat -lntp | grep -E '8766|8791'
echo '=== ENV (safe) ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_|SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_PAPER)=' /etc/bilshenz.env
python3 - <<'PY'
from pathlib import Path
for ln in Path('/etc/bilshenz.env').read_text().splitlines():
    if ln.startswith('BINANCE_API_KEY=') or ln.startswith('BINANCE_API_SECRET='):
        k,v=ln.split('=',1); v=v.strip().strip('"').strip("'")
        print(k, 'len', len(v))
print('session', Path('/var/lib/bilshenz/binance-session.json').exists())
PY

echo '=== HEALTH (3s) ==='
curl -sS -m 3 -o /tmp/h.json -w 'http=%{http_code} time=%{time_total}\n' http://127.0.0.1:8766/health
echo '=== JOURNAL last errors ==='
journalctl -u bilshenz-binance-api --no-pager -n 40 --since '2 hours ago' 2>/dev/null | tail -n 40
echo '=== LOG tail ==='
tail -n 60 /var/log/bilshenz/binance-api.log
echo '=== ERRORS ==='
tail -n 40 /var/log/bilshenz/errors.log
'''
_, o, e = c.exec_command(CMD, timeout=45)
out = o.read().decode("utf-8", "replace")
Path(__file__).with_name("_tn-diag1.txt").write_text(out, encoding="utf-8")
print(out.encode("ascii", "replace").decode("ascii")[-12000:])
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
