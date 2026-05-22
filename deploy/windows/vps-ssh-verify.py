#!/usr/bin/env python3
import os, sys
import paramiko

HOST = os.environ.get("VPS_HOST", "104.194.140.203")
USER = os.environ.get("VPS_USER", "Administrator")
PW = os.environ.get("VPS_PW", "")
if not PW:
    print("Set VPS_PW", file=sys.stderr)
    sys.exit(2)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

for port in (22, 2222):
    try:
        client.connect(
            HOST, port=port, username=USER, password=PW,
            timeout=25, look_for_keys=False, allow_agent=False,
        )
        print(f"SSH OK port {port}")
        break
    except Exception as e:
        print(f"port {port}: {e}")
else:
    sys.exit(1)

cmds = [
    "hostname",
    "powershell -NoProfile -Command \"if (Test-Path C:/opt/bilshenz) { 'repo OK' } else { 'repo MISSING' }\"",
    "powershell -NoProfile -Command \"try { (Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 6) | ConvertTo-Json -Compress } catch { 'mt5-api down' }\"",
    "powershell -NoProfile -Command \"try { (Invoke-RestMethod http://127.0.0.1:8791/health -TimeoutSec 4).ok } catch { 'desk down' }\"",
    "powershell -NoProfile -Command \"Get-ScheduledTask Bilshenz-* -ErrorAction SilentlyContinue | Select-Object TaskName,State | Format-Table -AutoSize | Out-String\"",
]
for cmd in cmds:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    print(f"\n--- {cmd[:50]} ---\n{out or stderr.read().decode('utf-8', errors='replace')[:200]}")

client.close()
