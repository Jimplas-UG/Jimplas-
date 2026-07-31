#!/usr/bin/env python3
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""
set -e
echo MATH
python3 - <<'PY'
entry=0.06469
exitp=0.06086
print('BANK_short_move_pct', round((entry-exitp)/entry*100,3))
print('BANK_tp', round(entry*0.975,6))
print('BANK_notional', round(3864*0.06469,2))
r_entry=0.08633
r_now=0.08716
print('RIF_adverse_pct', round((r_now-r_entry)/r_entry*100,3))
print('RIF_notional', round(2895*0.08633,2))
print('RIF_long1_trigger', round(r_entry*1.02,6))
PY
echo LOGS
ls /var/log/bilshenz 2>/dev/null || true
ls /var/log/tradingbot 2>/dev/null || true
journalctl -u bilshenz-binance-api -n 40 --no-pager 2>&1 | tail -n 40
echo GREP
grep -R -E 'scanner SHORT|RIFUSDT|BANKUSDT|Pending|entered' /var/log/bilshenz /var/log/tradingbot 2>/dev/null | tail -n 50 || true
"""
def main():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
if __name__ == "__main__":
    raise SystemExit(main())
