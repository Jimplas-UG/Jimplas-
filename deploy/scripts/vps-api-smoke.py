#!/usr/bin/env python3
"""Full API smoke with correct Bearer auth."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(
        "set -a; . /etc/bilshenz.env; set +a; "
        "python3 - <<'PY'\n"
        "import os,json,urllib.request,urllib.error,time\n"
        "DESK=os.environ.get('DESK_API_KEY','')\n"
        "base='http://127.0.0.1:8791'\n"
        "bbase='http://127.0.0.1:8766'\n"
        "H={'Authorization': f'Bearer {DESK}'}\n"
        "\n"
        "def call(url, method='GET', body=None, headers=None):\n"
        "  data=None if body is None else json.dumps(body).encode()\n"
        "  req=urllib.request.Request(url,data=data,method=method,headers=headers or {})\n"
        "  if data is not None: req.add_header('Content-Type','application/json')\n"
        "  try:\n"
        "    with urllib.request.urlopen(req,timeout=25) as r:\n"
        "      return r.status, r.read()[:500].decode('utf-8','replace')\n"
        "  except urllib.error.HTTPError as e:\n"
        "    return e.code, e.read()[:500].decode('utf-8','replace')\n"
        "  except Exception as e:\n"
        "    return 0, str(e)\n"
        "\n"
        "email=f'apk_e2e_{os.getpid()}@bilshenz.test'\n"
        "tests=[]\n"
        "tests.append(('desk_health',)+call(f'{base}/health'))\n"
        "tests.append(('binance_health',)+call(f'{bbase}/health'))\n"
        "tests.append(('desk_binance_proxy',)+call(f'{base}/v1/binance/health', headers=H))\n"
        "tests.append(('auth_login_bad',)+call(f'{base}/v1/auth/login','POST',{'email':'nobody@ex.com','password':'x'}))\n"
        "reg=call(f'{base}/v1/auth/register','POST',{'email':email,'password':'Test1234!','fullName':'APK Smoke'}, H)\n"
        "tests.append(('auth_register',)+reg)\n"
        "login=call(f'{base}/v1/auth/login','POST',{'email':email,'password':'Test1234!'})\n"
        "tests.append(('auth_login',)+login)\n"
        "tok=None\n"
        "try:\n"
        "  tok=json.loads(login[1]).get('accessToken')\n"
        "except: pass\n"
        "if tok:\n"
        "  tests.append(('auth_me',)+call(f'{base}/v1/auth/me', headers={'Authorization': f'Bearer {tok}'}))\n"
        "tests.append(('download_meta',)+call(f'{base}/download'))\n"
        "for name,code,body in tests:\n"
        "  print(f'{name}\\t{code}\\t{body[:240].replace(chr(10),\" \")}')\n"
        "PY\n"
        "echo === systemd ===\n"
        "systemctl is-active bilshenz-binance-api bilshenz-desk-api\n"
        "systemctl is-enabled bilshenz-binance-api bilshenz-desk-api\n"
        "ls -lh /opt/bilshenz/frontend/dist/bilshenz-release.apk\n"
        "cat /opt/bilshenz/frontend/dist/bilshenz-release.sha256 2>/dev/null || true\n",
        timeout=120,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
