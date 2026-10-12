#!/usr/bin/env python3
"""Live FRA forensic: open book, halt, recent violation/exec lines."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
echo ===SERVICES===
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
echo ===HEALTH===
curl -sS http://127.0.0.1:8766/health | $PY -c "
import sys,json
h=json.load(sys.stdin); sc=h.get('scanner') or {}
print('mode',h.get('mode'),'conn',h.get('connected'))
for k in sorted(sc):
    if any(x in k.lower() for x in ('can_','safe','halt','stuck','over','part','exec','rule','err','strategy','block')):
        print(k,'=',sc.get(k))
"
echo ===POS===
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions | $PY -c "
import sys,json
d=json.load(sys.stdin)
ps=d.get('positions') or []
openp=[p for p in ps if abs(float(p.get('volume') or p.get('positionAmt') or 0))>1e-12]
print('open',len(openp),'stale',d.get('stale'))
for p in openp:
    print(p.get('symbol'), p.get('positionSide') or p.get('side'), 'qty', p.get('volume') or p.get('positionAmt'), 'entry', p.get('entryPrice') or p.get('price_open'), 'lev', p.get('leverage'), 'pnl', p.get('unRealizedProfit') or p.get('profit'))
"
echo ===STATUS===
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status | $PY -c "
import sys,json
d=json.load(sys.stdin)
a=d.get('account') or {}
print('bal',a.get('balance'),'profit',a.get('profit'),'can',d.get('can_execute'),'halt',d.get('user_exec_halted'),'block',d.get('exec_block'),'mode',d.get('mode'))
"
echo ===RECENT_EVENTS===
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status | $PY -c "
import sys,json
d=json.load(sys.stdin)
ev=d.get('execution_events') or (d.get('scanner') or {}).get('execution_events') or []
for e in (ev[:12] if isinstance(ev,list) else []):
    print(e.get('ts'), e.get('symbol'), e.get('leg'), e.get('side'), e.get('stage'), e.get('quantity'), e.get('fill_price'), e.get('error'))
" 2>/dev/null || true
echo ===LOG_VIOLATIONS===
grep -E 'SAFE_MODE|OVERSIZE|PARTIAL_CLOSE|SOLO_EXIT|INVALIDATION|long_residual|force_flat|ack_missing|CLOSE_INCOMPLETE|REFUSE_RESUME|emergency|kernel_|NAKED|orphan|PORTAL|-4005|-4131|LONG1_PULLBACK|LONG2_PULLBACK|PAIR_CLOSE|RESCUE|SMART_EXIT|SHORT_TP' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 100
echo ===DEPLOYED_MARKERS===
cd /opt/bilshenz/binance_trading_system/python
$PY - <<'PY'
import inspect
from frozen_strategy import assert_frozen_contract
import momentum_scanner as ms
import binance_connector as bc
snap=assert_frozen_contract()
print('contract', snap['strategy_id'], snap['ops']['partition_usd'])
print('resolve', hasattr(bc.BinanceConnector,'_resolve_executed_qty'))
print('safe_mode', 'SAFE_MODE' in open(ms.__file__,encoding='utf-8').read())
print('close_incomplete', 'CLOSE_INCOMPLETE' in open(ms.__file__,encoding='utf-8').read())
print('solo', hasattr(ms.MomentumScanner,'_solo_hedge_exit_allowed'))
src=inspect.getsource(ms.MomentumScanner._manage_positions)
print('naked_force_10x', 'target = LONG1_LEVERAGE' in src)
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()


if __name__ == "__main__":
    main()
