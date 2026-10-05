#!/usr/bin/env python3
"""Locate bridge python + probe new Binance WS URLs on FRA."""
from __future__ import annotations

import json
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

FIND = r"""
set -e
echo '=== unit ==='
systemctl list-units --type=service --all 2>/dev/null | grep -iE 'bilshenz|binance|bridge' || true
echo '=== ExecStart ==='
for u in bilshenz-bridge.service binance-bridge.service bilshenz.service; do
  systemctl cat "$u" 2>/dev/null | head -30 && break
done
echo '=== py ==='
ps aux | grep -E 'main.py|uvicorn|binance' | grep -v grep | head -5
"""

PROBE = r'''
import asyncio, json, time, urllib.request, sys
import websockets

async def probe(url, secs=3.2):
    n=0; first=None; last=None; err=None; sample=None
    t0=time.monotonic()
    try:
        async with websockets.connect(url, ping_interval=8, ping_timeout=12, open_timeout=8) as ws:
            while time.monotonic()-t0 < secs:
                try:
                    raw=await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                n+=1
                now=time.monotonic()-t0
                if first is None: first=round(now,3)
                last=round(now,3)
                if sample is None:
                    try:
                        p=json.loads(raw)
                        if isinstance(p, list) and p:
                            sample={"type":"arr","n":len(p),"s":p[0].get("s"),"c":p[0].get("c")}
                        elif isinstance(p, dict):
                            sample={"s":p.get("s"),"b":p.get("b"),"a":p.get("a"),"e":p.get("e"),"stream":p.get("stream")}
                    except Exception:
                        sample={"raw_len":len(raw)}
    except Exception as e:
        err=str(e)[:200]
    return {"url":url,"msgs":n,"first_s":first,"last_s":last,"err":err,"sample":sample}

async def main():
    urls=[
        "wss://fstream.binance.com/ws/!miniTicker@arr",
        "wss://fstream.binance.com/market/ws/!miniTicker@arr",
        "wss://fstream.binance.com/public/ws/!miniTicker@arr",
        "wss://fstream.binance.com/ws/btcusdt@bookTicker",
        "wss://fstream.binance.com/public/ws/btcusdt@bookTicker",
        "wss://fstream.binance.com/market/ws/btcusdt@bookTicker",
    ]
    out=[await probe(u) for u in urls]
    t0=time.time()
    with urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT", timeout=5) as r:
        j=json.loads(r.read())
    print(json.dumps({"probes":out,"rest_btc":j,"rest_rtt_ms":round((time.time()-t0)*1000,1)}, indent=2))

asyncio.run(main())
'''


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=20)
    try:
        i, o, e = c.exec_command(FIND, timeout=30)
        print(o.read().decode("utf-8", "replace"))
        print(e.read().decode("utf-8", "replace")[-500:])

        # Prefer service WorkingDirectory venv
        i2, o2, e2 = c.exec_command(
            "PY=$(systemctl show -p ExecStart bilshenz-bridge.service 2>/dev/null | head -1); "
            "echo \"$PY\"; "
            "for p in /opt/bilshenz/venv/bin/python /opt/bilshenz/.venv/bin/python "
            "/opt/bilshenz/binance_trading_system/.venv/bin/python "
            "/opt/bilshenz/binance_trading_system/venv/bin/python; do "
            "[ -x \"$p\" ] && echo FOUND:$p; done; "
            "tr '\\0' ' ' </proc/$(pgrep -f 'binance_trading_system/python/main.py' | head -1)/cmdline 2>/dev/null; echo",
            timeout=20,
        )
        info = o2.read().decode("utf-8", "replace")
        print(info)

        py = "python3"
        for line in info.splitlines():
            if line.startswith("FOUND:"):
                py = line.split("FOUND:", 1)[1].strip()
                break
        # Also parse ExecStart
        if "ExecStart=" in info:
            for part in info.replace("=", " ").split():
                if part.endswith("/python") or part.endswith("/python3"):
                    py = part
                    break

        print(f"USING_PY={py}")
        i3, o3, e3 = c.exec_command(f"{py} -", timeout=90)
        i3.write(PROBE.encode())
        i3.channel.shutdown_write()
        print(o3.read().decode("utf-8", "replace") or e3.read().decode("utf-8", "replace"))
    finally:
        c.close()


if __name__ == "__main__":
    main()
