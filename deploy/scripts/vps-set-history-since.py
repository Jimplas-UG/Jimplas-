#!/usr/bin/env python3
"""Set TRADE_HISTORY_SINCE on VPS and restart binance-api."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
SINCE = os.environ.get("TRADE_HISTORY_SINCE", "2026-07-14")

REMOTE = f"""#!/usr/bin/env python3
from pathlib import Path
p = Path("/etc/bilshenz.env")
lines = []
if p.exists():
    lines = [l for l in p.read_text().splitlines() if not l.startswith("TRADE_HISTORY_SINCE=")]
lines.append("TRADE_HISTORY_SINCE={SINCE}")
p.write_text("\\n".join(lines) + "\\n")
print("TRADE_HISTORY_SINCE={SINCE}")
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/set-history-since.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, stdout, stderr = client.exec_command(
        "python3 /tmp/set-history-since.py && systemctl restart bilshenz-binance-api && sleep 2 && "
        "systemctl is-active bilshenz-binance-api && grep TRADE_HISTORY_SINCE /etc/bilshenz.env",
        timeout=60,
    )
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(out)
    if err.strip():
        print(err, file=sys.stderr)
    client.close()
    return 0 if "active" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
