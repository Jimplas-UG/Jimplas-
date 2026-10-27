#!/usr/bin/env python3
"""Confirm desk is not weight-stalling: snapshot + 90s recheck."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, time, pathlib, urllib.request, re, subprocess, collections

def snap(label):
    tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
    sc=h.get('scanner') or {}
    uds=h.get('user_data_stream') or {}
    feed=sc.get('feed') or sc.get('market') or {}
    ban_left=0.0
    p=pathlib.Path('/var/lib/bilshenz/rest-ban.json')
    if p.exists():
        b=json.loads(p.read_text()); ban_left=max(0.0, float(b.get('until_epoch') or 0)-time.time())
    # scanner stream internals if present
    ws = sc.get('ws_connected')
    if ws is None:
        ws = (sc.get('stream') or {}).get('ws_connected')
    rest_poll = sc.get('rest_poll_active')
    if rest_poll is None:
        rest_poll = (sc.get('stream') or {}).get('rest_poll_active')
    print(f'=== {label} {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} ===')
    print('connected', h.get('connected'), 'cool', h.get('rest_cool_s'),
          'can_execute', sc.get('can_execute'), 'exec_block', sc.get('exec_block'),
          'ban_left', round(ban_left,1))
    print('enabled', sc.get('enabled'), 'tracked', sc.get('symbols_tracked'),
          'active', sc.get('active_symbol'), 'open', h.get('open_positions'),
          'partition', sc.get('partition_usd'),
          'reconcile_ms', sc.get('reconcile_idle_ms') or sc.get('reconcile_ms'))
    print('user_ws', uds.get('ws_connected'), 'scanner_ws', ws, 'rest_poll', rest_poll)
    print('warning', (h.get('warning') or '')[:120])
    return {
        'can': bool(sc.get('can_execute')),
        'cool': float(h.get('rest_cool_s') or 0),
        'ban': ban_left,
        'connected': bool(h.get('connected')),
        'block': sc.get('exec_block'),
        'reconcile': sc.get('reconcile_idle_ms') or sc.get('reconcile_ms'),
    }

def log_window(seconds):
    since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-seconds))
    lines=[]
    with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
        for l in fh:
            if l.startswith('2026-') and l[:16] >= since[:16]:
                lines.append(l)
    weights=[]
    hard=soft=ban=pos_spam=0
    for l in lines:
        if '418 IP ban' in l: ban += 1
        if 'HARD' in l and 'weight' in l.lower(): hard += 1
        if 'SOFT' in l and 'weight' in l.lower(): soft += 1
        if 'positions:' in l: pos_spam += 1
        m=re.search(r'used weight (\d+(?:\.\d+)?)/2400', l)
        if m: weights.append(float(m.group(1)))
        # also catch "weight=NNNN" style
        m2=re.search(r'weight[= ](\d{3,4})(?:/2400)?', l, re.I)
        if m2:
            try: weights.append(float(m2.group(1)))
            except: pass
    # path hints from weight lines
    paths=collections.Counter()
    for l in lines:
        m=re.search(r"top=\[(.*?)\]", l)
        if m:
            for part in re.findall(r"\('([^']+)',\s*(\d+)\)", m.group(1)):
                paths[part[0]] += int(part[1])
    print(f'LOG_{seconds}s lines', len(lines), '418', ban, 'HARD', hard, 'SOFT', soft, 'pos_warn', pos_spam)
    if weights:
        print(f'WEIGHT_{seconds}s max', max(weights), 'last', weights[-1], 'n', len(weights),
              'over1600', sum(1 for w in weights if w>=1600), 'over2100', sum(1 for w in weights if w>=2100))
    else:
        print(f'WEIGHT_{seconds}s quiet')
    if paths:
        print('PATH_TOP', paths.most_common(6))
    # recent stall/cool samples
    hits=[l for l in lines if any(x in l for x in ('HARD', 'SOFT', '418 IP', 'can_execute False', 'rest cool', 'SAFE_MODE'))]
    print('STALL_SAMPLE')
    for l in hits[-6:]:
        print(' ', l.strip()[:220])
    return {'hard': hard, 'soft': soft, 'ban': ban, 'wmax': max(weights) if weights else 0.0, 'lines': len(lines)}

s1 = snap('T0')
print('--- services ---')
print('active', subprocess.getoutput('systemctl is-active bilshenz-binance-api bilshenz-forward-bot bilshenz-desk-api'))
print('enabled_fwd', subprocess.getoutput('systemctl is-enabled bilshenz-forward-bot 2>/dev/null || true'))
env=open('/etc/bilshenz.env').read()
print('FORWARD_DRY_RUN', [l for l in env.splitlines() if 'FORWARD_DRY_RUN' in l][:2])
print('SCANNER_RECONCILE', [l for l in env.splitlines() if 'SCANNER_RECONCILE' in l][:2])
# code markers
conn=open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read()
print('CODE_SHARE', 'POSITIONS_SHARE' in conn, 'host_scoped' in conn.lower() or 'weight_host' in conn.lower() or '_weight_by_host' in conn or 'WEIGHT_HOST' in conn)
print('CODE_FLAT_SHARE', 'POSITIONS_SHARE_FLAT' in conn or 'SHARE_FLAT' in conn)

w15 = log_window(900)  # 15m
print('--- wait 90s ---')
time.sleep(90)
s2 = snap('T90')
w2 = log_window(120)

ok = (
    s1['can'] and s2['can']
    and s1['cool'] <= 0.25 and s2['cool'] <= 0.25
    and s1['ban'] <= 0 and s2['ban'] <= 0
    and s1['connected'] and s2['connected']
    and w2['hard'] == 0 and w2['ban'] == 0
    and w2['wmax'] < 2100
    and 'inactive' in subprocess.getoutput('systemctl is-active bilshenz-forward-bot')
)
print('=== VERDICT ===')
print('PASS' if ok else 'FAIL')
print('detail', {
    't0': s1, 't90': s2,
    'w15_hard': w15['hard'], 'w15_soft': w15['soft'], 'w15_max': w15['wmax'],
    'w2_hard': w2['hard'], 'w2_soft': w2['soft'], 'w2_max': w2['wmax'],
})
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    c.close()

if __name__ == "__main__":
    main()
