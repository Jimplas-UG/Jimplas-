#!/usr/bin/env python3
from pathlib import Path
import paramiko
HOST='159.223.29.223'
KEY=Path.home()/'.ssh'/'id_ed25519'
CMD=r"""
grep '2026-09-30T06:1[6-9]' /var/log/bilshenz/binance-api.log | grep USUSDT | head -n 25
echo ===
grep '2026-09-30T06:2[89]' /var/log/bilshenz/binance-api.log | grep USUSDT | head -n 25
echo ===
grep '2026-09-30T06:30' /var/log/bilshenz/binance-api.log | grep USUSDT | head -n 20
echo ===MOVR_ADV===
grep '2026-09-30T07:13' /var/log/bilshenz/binance-api.log | grep -E 'MOVR|adverse|LONG2' | head -n 30
echo ===DEEP_357===
grep '2026-09-30T03:5[5-9]' /var/log/bilshenz/binance-api.log | grep DEEP | head -n 30
"""
pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username='root', pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
_,o,e=c.exec_command(CMD, timeout=60)
print(o.read().decode())
c.close()
