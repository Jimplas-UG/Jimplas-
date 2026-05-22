# Upload deploy bundle and run install on Ubuntu VPS (password via env, not saved)
# Usage: $env:VPS_PW='your-root-password'; .\deploy\deploy-from-windows.ps1
param(
  [string]$Host = '68.183.35.165',
  [string]$User = 'root'
)
$ErrorActionPreference = 'Stop'
if (-not $env:VPS_PW) { throw 'Set VPS_PW first: $env:VPS_PW="..."' }

pip install paramiko -q
$py = @"
import os, paramiko, pathlib
host, user, pw = '$Host', '$User', os.environ['VPS_PW']
root = pathlib.Path(r'$((Get-Location).Path)')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=20)
sftp = client.open_sftp()
remote = '/tmp/bilshenz-deploy'
try:
    client.exec_command(f'mkdir -p {remote}')
except Exception:
    pass
for rel in ['install-production.sh', 'bilshenz.env.example', 'watchdog.ts']:
    local = root / 'deploy' / rel
    sftp.put(str(local), f'{remote}/{rel}')
for svc in (root / 'deploy' / 'systemd').glob('*.service'):
    sftp.put(str(svc), f'{remote}/{svc.name}')
sftp.close()
cmd = f'chmod +x {remote}/install-production.sh && APP_DIR=/opt/bilshenz bash {remote}/install-production.sh'
stdin, stdout, stderr = client.exec_command(cmd, timeout=600)
print(stdout.read().decode())
err = stderr.read().decode()
if err: print(err, file=__import__('sys').stderr)
code = stdout.channel.recv_exit_status()
client.close()
raise SystemExit(code)
"@
python -c $py
Write-Host "Done. SSH in and edit /etc/bilshenz.env then: systemctl restart bilshenz-*"
