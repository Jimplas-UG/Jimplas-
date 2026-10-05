#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
set +e
python3 -c 'from pathlib import Path; b=Path("/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh").read_bytes(); print("cr", b.count(b"\r"), "len", len(b))'
pkill -f build-apk-fra.sh
pkill -f 'gradlew assembleRelease'
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_PID=$!
sleep 12
ps -ef | grep -E 'build-apk-fra|gradlew|expo|npm' | grep -v grep | head -n 15
echo ---NOHUP---
cat /var/log/bilshenz/apk-build-nohup.out
echo ---LOG---
tail -n 30 /var/log/bilshenz/apk-build.log
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode())
print(e.read().decode()[-800:])
c.close()
