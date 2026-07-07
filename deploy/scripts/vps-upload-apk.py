#!/usr/bin/env python3
"""Upload APK to VPS via SFTP."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
LOCAL = os.environ.get(
    "APK_PATH",
    os.path.join(os.path.dirname(__file__), "../../frontend/dist/bilshenz-release-signed.apk"),
)
REMOTE = "/opt/bilshenz/frontend/dist/bilshenz-release.apk"


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    local = os.path.abspath(LOCAL)
    if not os.path.isfile(local):
        print(f"APK not found: {local}", file=sys.stderr)
        return 1
    import paramiko

    transport = paramiko.Transport((HOST, 22))
    transport.connect(username=USER, password=PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.put(local, REMOTE)
    sftp.close()
    transport.close()
    print(f"UPLOADED {local} -> {REMOTE} ({os.path.getsize(local)} bytes)")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(
        "curl -s http://127.0.0.1:8791/download && echo && ls -lh /opt/bilshenz/frontend/dist/bilshenz-release.apk",
        timeout=60,
    )
    print(stdout.read().decode())
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
