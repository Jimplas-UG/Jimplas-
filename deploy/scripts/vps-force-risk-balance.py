#!/usr/bin/env python3
"""Force balanced short partition sizing on VPS risk JSON + restart API."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
python3 - <<'PY'
import json, os
path = "/var/lib/bilshenz/scanner-risk.json"
raw = {}
if os.path.isfile(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh) or {}
raw["partition_usd"] = float(raw.get("partition_usd") or 100)
raw["short_pct"] = 50.0
raw["long1_pct"] = 12.5
raw["long2_pct"] = 12.5
raw["locked"] = False
os.makedirs(os.path.dirname(path), exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(raw, fh, indent=2)
os.replace(tmp, path)
print("UPDATED", raw)
PY
systemctl restart bilshenz-binance-api
sleep 4
systemctl is-active bilshenz-binance-api
cat /var/lib/bilshenz/scanner-risk.json
curl -s http://127.0.0.1:8766/health | python3 -c "import sys,json;h=json.load(sys.stdin);sc=h.get('scanner') or {};print('exec',sc.get('can_execute'),'risk',sc.get('risk') or sc.get('partition') or {k:sc.get(k) for k in sc if 'pct' in k.lower() or 'partition' in k.lower() or 'risk' in k.lower()})"
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
