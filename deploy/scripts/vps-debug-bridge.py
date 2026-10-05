#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "161.35.112.53"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
systemctl status bilshenz-binance-api --no-pager -l | head -40
echo '=== JOURNAL ==='
journalctl -u bilshenz-binance-api -n 80 --no-pager
echo '=== APP LOG ==='
tail -n 60 /var/log/bilshenz/binance-api.log 2>/dev/null || true
tail -n 40 /var/log/bilshenz/errors.log 2>/dev/null || true
echo '=== ENV KEYS ==='
grep -E '^[A-Z0-9_]+=' /etc/bilshenz.env | cut -d= -f1 | sort
"""

key = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=60)
out = o.read().decode("utf-8", errors="replace").encode("ascii", "replace").decode("ascii")
err = e.read().decode("utf-8", errors="replace").encode("ascii", "replace").decode("ascii")
print(out)
if err.strip():
    print("STDERR:", err[-2000:])
c.close()
