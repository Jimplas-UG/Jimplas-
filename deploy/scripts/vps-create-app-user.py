#!/usr/bin/env python3
import json
import urllib.error
import urllib.request
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
EMAIL = "amos@bilshenz.local"
PASSWORD = "Bilshenz2026!"
FULL_NAME = "Amos Kole"


def http_json(url, data, timeout=20):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def main() -> int:
    # Fix auth on server if needed, then register locally via public IP
    key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(
        "tail -n 20 /var/log/bilshenz/desk-api.log; ls -la /opt/bilshenz/backend/auth/data/",
        timeout=30,
    )
    print(o.read().decode("utf-8", "replace"))
    print(e.read().decode("utf-8", "replace")[-400:])
    c.close()

    print("register…")
    st, j = http_json(
        f"http://{HOST}:8791/v1/auth/register",
        {
            "email": EMAIL,
            "password": PASSWORD,
            "confirmPassword": PASSWORD,
            "fullName": FULL_NAME,
        },
    )
    print(st, j)
    print("login…")
    st, j = http_json(
        f"http://{HOST}:8791/v1/auth/login",
        {"email": EMAIL, "password": PASSWORD},
    )
    # don't dump full JWT
    if isinstance(j, dict) and j.get("accessToken"):
        print(st, {"ok": True, "email": EMAIL, "hasToken": True, "user": (j.get("user") or {}).get("email")})
    else:
        print(st, j)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
