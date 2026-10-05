#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
grep -E '^(BINANCE_TESTNET|BINANCE_PAPER|FORWARD_DRY_RUN|SCANNER_EXEC)=' /etc/bilshenz.env
echo '---'
python3 - <<'PY'
import os
# simulate what service sees
from pathlib import Path
for line in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1)
        os.environ.setdefault(k,v)
print('env TESTNET', os.environ.get('BINANCE_TESTNET'))
PY
# status endpoint
curl -sS --max-time 10 http://127.0.0.1:8766/api/status 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ['ok','connected','testnet','mode','server','error']})" || echo no_status
# check process environ
tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value bilshenz-binance-api)/environ 2>/dev/null | grep -E 'BINANCE_TESTNET|TESTNET' || echo 'no proc env'
tail -n 25 /var/log/bilshenz/binance-api.log | tr -cd '\11\12\15\40-\176'
"""
_, o, e = c.exec_command(CMD, timeout=45)
print(o.read().decode("ascii", "replace"))
print(e.read().decode("ascii", "replace")[-800:])
c.close()
