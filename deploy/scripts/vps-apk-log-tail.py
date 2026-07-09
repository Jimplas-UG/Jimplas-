#!/usr/bin/env python3
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
if not PASSWORD:
    sys.exit(1)
import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
_, o, _ = c.exec_command("tail -n 80 /var/log/bilshenz/apk-build.log | tr -cd '\\11\\12\\15\\40-\\176'", timeout=60)
print(o.read().decode("utf-8", "replace"))
_, o, _ = c.exec_command("grep -nE 'FATAL|FAILED|error:|Error|Preflight|DONE|npm ERR' /var/log/bilshenz/apk-build.log | tail -n 30", timeout=60)
print('---MARKERS---')
print(o.read().decode("utf-8", "replace"))
c.close()
