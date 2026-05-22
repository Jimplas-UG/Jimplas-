# Run on YOUR PC when SSH to VPS works:  .\deploy-now.ps1
$ErrorActionPreference = 'Stop'
if (-not $env:VPS_PW) {
  $sec = Read-Host 'VPS password (not saved)' -AsSecureString
  $env:VPS_PW = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
$env:VPS_HOST = if ($env:VPS_HOST) { $env:VPS_HOST } else { '104.194.140.203' }
$env:VPS_USER = if ($env:VPS_USER) { $env:VPS_USER } else { 'Administrator' }

Write-Host "Testing SSH to $env:VPS_HOST ..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$env:VPS_USER@$env:VPS_HOST" "hostname"
if ($LASTEXITCODE -ne 0) { throw 'SSH failed from this PC — check cloud firewall allows YOUR IP on port 22' }

$here = Split-Path $PSScriptRoot -Parent | Split-Path -Parent
python (Join-Path $here 'deploy\windows\remote-vps-deploy.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python (Join-Path $here 'deploy\windows\vps-ssh-verify.py')
Write-Host 'Deploy complete. Log into MT5 Exness on VPS, then set FORWARD_DRY_RUN=0 when ready.' -ForegroundColor Green
