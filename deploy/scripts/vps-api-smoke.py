#!/usr/bin/env python3
"""Smoke-test desk + binance APIs on the VPS."""
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def http(url, method="GET", body=None, headers=None, timeout=20):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw
    except Exception as e:
        return 0, str(e)


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(
        "grep -E '^(DESK_API_KEY|BRIDGE_TOKEN)=' /etc/bilshenz.env | sed 's/=.*/=***/'",
        timeout=20,
    )
    print(stdout.read().decode())
    _, stdout, _ = client.exec_command(
        "set -a; . /etc/bilshenz.env; set +a; "
        "python3 - <<'PY'\n"
        "import os,json,urllib.request,urllib.error\n"
        "DESK=os.environ.get('DESK_API_KEY','')\n"
        "BRIDGE=os.environ.get('BRIDGE_TOKEN','')\n"
        "base='http://127.0.0.1:8791'\n"
        "bbase='http://127.0.0.1:8766'\n"
        "\n"
        "def call(url, method='GET', body=None, headers=None):\n"
        "  data=None if body is None else json.dumps(body).encode()\n"
        "  req=urllib.request.Request(url,data=data,method=method,headers=headers or {})\n"
        "  if data is not None: req.add_header('Content-Type','application/json')\n"
        "  try:\n"
        "    with urllib.request.urlopen(req,timeout=20) as r:\n"
        "      return r.status, r.read()[:400].decode('utf-8','replace')\n"
        "  except urllib.error.HTTPError as e:\n"
        "    return e.code, e.read()[:400].decode('utf-8','replace')\n"
        "  except Exception as e:\n"
        "    return 0, str(e)\n"
        "\n"
        "tests=[]\n"
        "tests.append(('desk_health',)+call(f'{base}/health'))\n"
        "tests.append(('binance_health',)+call(f'{bbase}/health'))\n"
        "tests.append(('desk_binance_proxy',)+call(f'{base}/v1/binance/health', headers={'x-api-key':DESK}))\n"
        "tests.append(('auth_login_bad',)+call(f'{base}/v1/auth/login', 'POST', {'email':'nobody@ex.com','password':'x'}, {'x-api-key':DESK}))\n"
        "tests.append(('auth_register_try',)+call(f'{base}/v1/auth/register', 'POST', {'email':'apk_smoke_'+str(os.getpid())+'@bilshenz.test','password':'Test1234!','name':'APK Smoke'}, {'x-api-key':DESK}))\n"
        "for name,code,body in tests:\n"
        "  print(f'{name}\\t{code}\\t{body[:220]}')\n"
        "PY",
        timeout=90,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = client.exec_command("true")  # keep connection shape
    # also check public without keys
    for url in [
        f"http://{HOST}:8766/health",
        f"http://{HOST}:8791/health",
        f"http://{HOST}:8791/download",
    ]:
        code, body = http(url)
        print(f"public\t{url}\t{code}\t{body[:180]}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
