#!/usr/bin/env python3
import os
import paramiko

PASSWORD = os.environ.get("VPS_PASSWORD", "")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("157.245.33.42", username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
cmd = r"""
grep -E 'SCANNER_(LONG_PULLBACK|SMART_EXIT|LONG1_PARTITION|LONG2_PARTITION|EXIT_COST)' /etc/bilshenz.env || true
echo ---
cat /var/lib/bilshenz/scanner-risk.json 2>/dev/null || true
echo ---
cd /opt/bilshenz && git log -1 --oneline
"""
_, o, e = c.exec_command(cmd, timeout=60)
print(o.read().decode())
err = e.read().decode()
if err.strip():
    print(err)
c.close()
