#!/usr/bin/env python3
"""Remote VPS status probe via SSH password."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = os.environ.get(
    "VPS_CMD",
    "systemctl is-active bilshenz-binance-api bilshenz-desk-api 2>/dev/null; "
    "echo '---'; "
    "curl -s --max-time 5 http://127.0.0.1:8766/health | head -c 400; echo; "
    "curl -s --max-time 5 http://127.0.0.1:8791/health; echo; "
    "curl -s --max-time 5 http://127.0.0.1:8791/download; echo; "
    "ls -lh /opt/bilshenz/frontend/dist/ 2>/dev/null || echo NO_DIST; "
    "echo '---LOG---'; "
    "tail -40 /var/log/bilshenz/apk-build.log 2>/dev/null || echo NO_APK_LOG; "
    "echo '---PS---'; "
    "pgrep -af 'gradle|sdkmanager|expo|npm' || echo no-build-proc; "
    "echo '---ENV---'; "
    "grep -E '^(DESK_API_KEY|BRIDGE_TOKEN|FORWARD_DRY_RUN|BINANCE_TESTNET|SCANNER_EXEC|HOST|PORT)=' /etc/bilshenz.env 2>/dev/null | sed 's/=.*/=***/'; "
    "echo '---UFW---'; "
    "ufw status 2>/dev/null | head -20; "
    "echo '---DISK---'; "
    "df -h / | tail -1; free -h | head -2",
)

def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, get_pty=True, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    client.close()
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    if err.strip():
        sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
    return code

if __name__ == "__main__":
    raise SystemExit(main())
