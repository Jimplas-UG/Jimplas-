#!/usr/bin/env python3
"""Repair corrupted /etc/bilshenz.env (single-line smash) and re-apply halt."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r'''
set -e
echo '=== backups ==='
ls -la /etc/bilshenz.env* /opt/bilshenz/deploy/**/bilshenz.env* 2>/dev/null | head -40
find /opt/bilshenz /root /var/backups -name 'bilshenz.env*' 2>/dev/null | head -40
# show raw corruption shape (no secrets)
python3 <<'PY'
from pathlib import Path
p=Path('/etc/bilshenz.env')
raw=p.read_text(encoding='utf-8', errors='replace')
print('len', len(raw), 'newlines', raw.count('\n'), 'literal_backslash_n', raw.count('\\n'))
# if smashed with literal \n sequences, split them
if raw.count('\n') <= 1 and '\\n' in raw:
    fixed=raw.replace('\\n','\n')
    print('REPAIR_LITERAL_BACKSLASH_N lines', len(fixed.splitlines()))
    Path('/etc/bilshenz.env.smashed.bak').write_text(raw, encoding='utf-8')
    Path('/etc/bilshenz.env').write_text(fixed if fixed.endswith('\n') else fixed+'\n', encoding='utf-8')
    print('REPAIRED')
elif raw.count('\n') <= 1:
    print('SMASHED_OTHER')
    # try split on KEY= patterns
    import re
    keys=re.findall(r'([A-Z][A-Z0-9_]*=)', raw)
    print('embedded_keys', keys[:40])
else:
    print('LOOKS_MULTILINE', len(raw.splitlines()))
PY
echo '=== after repair key lens ==='
python3 <<'PY'
from pathlib import Path
raw=Path('/etc/bilshenz.env').read_text(encoding='utf-8', errors='replace')
print('lines', len(raw.splitlines()), 'newlines', raw.count('\n'))
for line in raw.splitlines():
    if not line.strip() or line.strip().startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    k=k.strip(); v=v.strip().strip('"').strip("'")
    if 'KEY' in k or 'SECRET' in k or 'TOKEN' in k:
        print(f'{k} len={len(v)}')
    elif k in ('SCANNER_EXEC','FORWARD_DRY_RUN','BINANCE_FORCE_MAINNET','BINANCE_TESTNET','TRADE_HISTORY_SINCE','FORWARD_DRY_RUN'):
        print(f'{k}={v}')
PY
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=40)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
