#!/usr/bin/env python3
"""Count 418/429 cool events and which REST paths fire most in recent bridge logs."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

REMOTE = r"""
import re, glob, os, time
from collections import Counter

files = sorted(glob.glob("/var/log/bilshenz/*.log"), key=os.path.getmtime)[-4:]
print("FILES", files)
lines = []
for f in files:
    try:
        with open(f, "r", errors="replace") as fh:
            lines.extend(fh.readlines()[-200000:])
    except Exception as e:
        print("ERR", f, e)

day = time.strftime("%Y-%m-%d", time.gmtime())
today = [l for l in lines if l.startswith(day)]
print("LINES_TODAY", len(today))

c418 = [l for l in today if "418" in l]
c429 = [l for l in today if "429" in l]
print("HITS_418", len(c418), "HITS_429", len(c429))

cool_set = [l for l in today if "REST cool" in l or "rest_cool" in l.lower() or "cooling" in l.lower()]
print("COOL_LINES", len(cool_set))

paths = Counter()
for l in today:
    m = re.search(r"(/fapi/v[0-9]/[A-Za-z/]+)", l)
    if m and ("418" in l or "429" in l or "weight" in l.lower() or "Too many" in l or "banned" in l.lower()):
        paths[m.group(1)] += 1
print("PATHS_ON_418_429", paths.most_common(15))

by_hour = Counter()
for l in c418:
    by_hour[l[11:13]] += 1
print("418_BY_HOUR", sorted(by_hour.items()))

ban = [l for l in today if "banned until" in l.lower() or "way too many" in l.lower()]
print("BAN_LINES", len(ban))
for l in ban[-5:]:
    print("  ", l.strip()[:300])

print("SAMPLE_418")
for l in c418[-12:]:
    print("  ", l.strip()[:300])

# signed REST call volume (any path) last hour
hr = time.strftime("%Y-%m-%dT%H", time.gmtime())
req = Counter()
for l in today:
    if not l.startswith(hr[:10]):
        continue
    m = re.search(r"(GET|POST|DELETE) (/fapi/v[0-9]/[A-Za-z/]+)", l)
    if m:
        req[m.group(2)] += 1
print("REQ_LOGGED_TODAY", req.most_common(15))
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_probe_418.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command("python3 /tmp/_probe_418.py", timeout=120)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
