#!/usr/bin/env python3
"""Show traffic sources right before each fresh 418 streak + REST-poll activity."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

REMOTE = r"""
import re, glob, os, time
from collections import Counter

files = sorted(glob.glob("/var/log/bilshenz/*.log"), key=os.path.getmtime)
lines = []
for f in files:
    try:
        with open(f, "r", errors="replace") as fh:
            lines.extend(fh.readlines()[-300000:])
    except Exception as e:
        print("ERR", f, e)
lines.sort(key=lambda l: l[:19])
day = time.strftime("%Y-%m-%d", time.gmtime())
today = [l for l in lines if l.startswith(day)]
print("REST_POLL_ACTIVE", sum(1 for l in today if "REST price poll ACTIVE" in l))
print("REST_POLL_FAIL", sum(1 for l in today if "REST price poll" in l and ("fail" in l or "error" in l)))
print("WS_DISCONNECT", sum(1 for l in today if "scanner stream disconnected" in l))

src = Counter()
for l in today:
    m = re.search(r"\[(\w+)\] ([A-Za-z_0-9]+)[ :(]", l)
    if m:
        src[m.group(1) + "." + m.group(2)] += 1
print("TOP_SOURCES", src.most_common(30))

engage = [i for i, l in enumerate(today) if "Binance 418 — cool" in l or "Binance 429 — cool" in l]
print("ENGAGE_COUNT", len(engage))
first = []
prev_t = None
for i in engage:
    t = today[i][:19]
    if prev_t is None or t[:16] != prev_t[:16]:
        first.append(i)
    prev_t = t
print("DISTINCT_MINUTES_ENGAGED", len(first))
for i in first[:3] + first[-2:]:
    print("--- onset", today[i][:19])
    for l in today[max(0, i - 25): i + 1]:
        print("   ", l.strip()[:220])

per_min = Counter(l[:16] for l in today if "Binance 418 — cool" in l)
print("ENGAGE_PER_MIN_TOP", per_min.most_common(8))
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_probe_418_onset.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command("python3 /tmp/_probe_418_onset.py", timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
