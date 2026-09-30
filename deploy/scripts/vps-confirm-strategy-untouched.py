#!/usr/bin/env python3
"""Confirm frozen strategy untouched — read-only audit."""
from pathlib import Path
import paramiko
import hashlib

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

LOCK_FILES = [
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/leverage_policy.py",
    "binance_trading_system/python/strategy_guards.py",
]

CMD = r"""
set +e
cd /opt/bilshenz/binance_trading_system/python
echo '=== FROZEN CONTRACT ==='
python3 - <<'PY'
from frozen_strategy import assert_frozen_contract, STRATEGY_ID, GAIN_THRESHOLD_PCT, RETRACE_ENTRY_PCT
from frozen_strategy import PRIMARY_LEVERAGE, RECOVERY_LEVERAGE, PRIMARY_PARTITION_PCT, RECOVERY_PARTITION_PCT
from frozen_strategy import LONG1_ADVERSE_PCT, LONG2_ADVERSE_PCT, SHORT_TP_PCT, LONG_TP_PCT
from frozen_strategy import PAIR_INVALIDATION_PCT, HEDGE_RESCUE_BUFFER_PCT, LONG_HEDGE_PULLBACK_PCT
try:
    snap = assert_frozen_contract()
    print('CONTRACT_OK', STRATEGY_ID)
    print('entry', GAIN_THRESHOLD_PCT, RETRACE_ENTRY_PCT)
    print('lev', PRIMARY_LEVERAGE, RECOVERY_LEVERAGE)
    print('parts%', PRIMARY_PARTITION_PCT, RECOVERY_PARTITION_PCT)
    print('adverse', LONG1_ADVERSE_PCT, LONG2_ADVERSE_PCT)
    print('tp', SHORT_TP_PCT, LONG_TP_PCT)
    print('inval', PAIR_INVALIDATION_PCT, 'rescue', HEDGE_RESCUE_BUFFER_PCT, 'long_pb', LONG_HEDGE_PULLBACK_PCT)
except Exception as e:
    print('CONTRACT_FAIL', type(e).__name__, e)
PY

echo '=== LIVE MODULE DEFAULTS ==='
python3 - <<'PY'
import momentum_scanner as ms
import leverage_policy as lev
print('GAIN', ms.GAIN_THRESHOLD_PCT, 'RETRACE', ms.RETRACE_ENTRY_PCT)
print('MIN_LIVE', ms.MIN_LIVE_ENTRY_PCT, 'LATCH_FRAC', ms.MIN_LIVE_VS_LATCH_FRAC)
print('L1', ms.LONG1_ADVERSE_PCT, 'L2', ms.LONG2_ADVERSE_PCT)
print('TP', ms.SHORT_TP_PCT, ms.LONG_TP_PCT)
print('PB long', ms.LONG_HEDGE_PULLBACK_PCT, 'short_trail', ms.SHORT_TRAIL_PULLBACK_PCT)
print('INVAL', ms.PAIR_INVALIDATION_PCT, 'RESCUE', ms.HEDGE_RESCUE_BUFFER_PCT)
print('PART%', ms.SHORT_PARTITION_PCT, ms.LONG1_PARTITION_PCT, ms.LONG2_PARTITION_PCT)
print('LEV', lev.SHORT_LEVERAGE, lev.LONG1_LEVERAGE, lev.LONG2_LEVERAGE)
print('status', ms.STATUS_SHORT, ms.STATUS_LONG1, ms.STATUS_LONG2)
print('magics', ms.MAGIC_SHORT, ms.MAGIC_LONG1, ms.MAGIC_LONG2)
PY

echo '=== CLOSE PATH COOL (ops only — not strategy) ==='
python3 - <<'PY'
import inspect, binance_connector as bc
src = inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
print('default_max_wait_in_sig', 'max_wait_s: float = 0.0' in src or 'max_wait_s=0' in src)
print('clears_cool_for_close', 'clear_rest_cool' in src)
print('no_strategy_thresholds_in_close_helper', 'GAIN_THRESHOLD' not in src and 'RETRACE' not in src)
PY

echo '=== RISK FILE ==='
cat /var/lib/bilshenz/scanner-risk.json 2>/dev/null
echo
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c "import sys,json;d=json.load(sys.stdin);s=d.get('scanner') or {};print('live_strategy',s.get('strategy_id') or s.get('strategy'),'partition',s.get('partition_usd'),'pct',s.get('short_partition_pct'),s.get('long1_partition_pct'),s.get('long2_partition_pct'),'mode',d.get('mode'),'exec',s.get('can_execute'),'block',s.get('exec_block'))"
"""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    print("=== LOCAL LOCK FILE HASHES ===")
    for rel in LOCK_FILES:
        p = ROOT / rel.replace("/", "\\")
        print(rel, sha(p) if p.exists() else "MISSING")

    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    print("=== LOCAL vs VPS HASHES ===")
    for rel in LOCK_FILES + [
        "binance_trading_system/python/momentum_scanner.py",
        "binance_trading_system/python/binance_connector.py",
    ]:
        local = ROOT / rel.replace("/", "\\")
        remote = f"/opt/bilshenz/{rel}"
        try:
            with sftp.file(remote, "rb") as f:
                rhash = hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception as e:
            rhash = f"ERR:{e}"
        lhash = sha(local) if local.exists() else "MISSING"
        print(f"{rel}: local={lhash} vps={rhash} {'MATCH' if lhash == rhash else 'DIFF'}")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-800:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
