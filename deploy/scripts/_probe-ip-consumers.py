#!/usr/bin/env python3
"""Which processes on the VPS talk to Binance (shared IP weight)."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo '--- services'
systemctl list-units --type=service --state=running --no-pager | grep -iE "bilshenz|bot|binance|python|node" || true
echo '--- timers'
systemctl list-timers --all --no-pager | grep -iE "bilshenz|bot|binance" || true
echo '--- cron'
crontab -l 2>/dev/null | grep -v '^#' || true
ls /etc/cron.d 2>/dev/null
echo '--- python/node procs'
ps -eo pid,etimes,pcpu,args --sort=-pcpu | grep -E "python|node" | grep -v grep | head -n 25
echo '--- 443 conns by process (sampled 5x)'
for i in 1 2 3 4 5; do ss -tnp state established '( dport = :443 )' 2>/dev/null | awk 'NR>1{print $4, $NF}'; sleep 1; done | sed -E 's/,fd=[0-9]+//g' | sort | uniq -c | sort -rn | head -n 30
echo '--- forward-bot env/cmd'
systemctl cat bilshenz-forward-bot --no-pager 2>/dev/null | grep -E "ExecStart|Environment" || true
echo '--- forward-bot log tail'
journalctl -u bilshenz-forward-bot --no-pager -n 15 2>/dev/null | cut -c1-240
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-600:])
    c.close()


if __name__ == "__main__":
    main()
