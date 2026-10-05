#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

# Starter script has NO 'build-apk-fra' string so pkill won't match this SSH session.
STARTER = b"""#!/bin/bash
set +e
kill $(cat /var/run/bilshenz-apk-build.pid 2>/dev/null) 2>/dev/null
pkill -f 'gradlew assembleRelease' 2>/dev/null
pkill -f 'expo prebuild' 2>/dev/null
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo $! > /var/run/bilshenz-apk-build.pid
echo STARTED:$(cat /var/run/bilshenz-apk-build.pid)
sleep 8
ps -p $(cat /var/run/bilshenz-apk-build.pid) -o pid,cmd || true
ps -ef | grep -E 'gradlew|expo prebuild|npm (ci|install)' | grep -v grep | head
tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || cat /var/log/bilshenz/apk-build-nohup.out
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
sftp = c.open_sftp()
with sftp.file("/tmp/start-bilshenz-apk.sh", "wb") as f:
    f.write(STARTER)
sftp.close()
_, o, e = c.exec_command("chmod +x /tmp/start-bilshenz-apk.sh && bash /tmp/start-bilshenz-apk.sh", timeout=45)
print(o.read().decode())
print(e.read().decode()[-800:])
c.close()
