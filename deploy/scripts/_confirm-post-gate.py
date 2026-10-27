#!/usr/bin/env python3
"""Confirm after boot settle: 3 min with zero positionRisk HARD and can_execute true."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, time, urllib.request, re, collections, subprocess

def health():
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
    return h, h.get('scanner') or {}

h,sc=health()
print('NOW', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
      'can', sc.get('can_execute'), 'cool', h.get('rest_cool_s'),
      'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
print('services', subprocess.getoutput('systemctl is-active bilshenz-binance-api bilshenz-forward-bot'))
src=open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read()
print('MARK account_book', '_positions_from_account_book' in src)
print('MARK testnet_never_full', 'never discretionary' in src or 'Testnet: never' in src or 'testnet", False))\n            return False' in src or 'getattr(self.cfg, "testnet"' in src)

# Show last boot weight events for context
since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-300))
print('RECENT_WEIGHT')
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if l.startswith('2026-') and l[:16]>=since[:16] and 'used weight' in l and 'paused' in l:
            print(' ', l.strip()[:240])

mark=time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())
print('MARK', mark, 'wait 180s (post-boot)')
time.sleep(180)
h2,sc2=health()
print('AFTER', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
      'can', sc2.get('can_execute'), 'cool', h2.get('rest_cool_s'),
      'block', sc2.get('exec_block'), 'active', sc2.get('active_symbol'))

hard=ban=soft=0; weights=[]; news=[]; paths=collections.Counter(); posrisk_hard=0
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if not l.startswith('2026-') or l[:19] < mark: continue
        if '418 IP ban' in l:
            ban+=1; news.append(l.strip()[:220])
        if 'used weight' in l:
            m=re.search(r'used weight (\d+(?:\.\d+)?)/2400', l)
            if m: weights.append(float(m.group(1)))
            top=re.search(r"top=\[(.*?)\]", l)
            if top:
                for part in re.findall(r"\('([^']+)',\s*(\d+)\)", top.group(1)):
                    paths[part[0]] += int(part[1])
            if 'HARD' in l:
                hard+=1; news.append(l.strip()[:220])
                if 'positionRisk' in l or (top and 'positionRisk' in top.group(1)):
                    posrisk_hard+=1
            elif 'paused' in l:
                soft+=1; news.append(l.strip()[:220])

print('POST_MARK HARD', hard, 'posRisk_HARD', posrisk_hard, 'SOFT', soft, '418', ban,
      'wmax', max(weights) if weights else 0, 'n', len(weights))
print('PATHS', paths.most_common(8))
for e in news[-12:]:
    print(' ', e)

ok = (
    sc2.get('can_execute') is True
    and float(h2.get('rest_cool_s') or 0) <= 0.25
    and ban == 0
    and posrisk_hard == 0
    and hard == 0
)
print('VERDICT', 'PASS' if ok else 'FAIL')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=240)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    c.close()

if __name__ == "__main__":
    main()
