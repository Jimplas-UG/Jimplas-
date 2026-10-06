#!/usr/bin/env python3
from pathlib import Path
import paramiko

CMD = r"""
systemctl is-active nginx 2>/dev/null || echo nginx_off
curl -sS -o /dev/null -w "www:%{http_code} size:%{size_download}\n" --max-time 20 http://127.0.0.1/bilshenz.apk || true
curl -sS -o /dev/null -w "download:%{http_code} size:%{size_download}\n" --max-time 30 http://127.0.0.1:8791/download/bilshenz.apk || true
curl -sS --max-time 8 http://127.0.0.1:8791/download; echo
stat -c 'apk %y %s' /opt/bilshenz/frontend/dist/bilshenz.apk
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print(err.encode("ascii", "replace").decode("ascii")[-400:])
c.close()
