# ONE command deploy - run on YOUR PC only. Does NOT open RDP (won't kick you off).
#Usage:
#  $env:VPS_PW = 'your-new-password-from-panel'
#  .\GODMODE-SSH-DEPLOY.ps1
$ErrorActionPreference = 'Stop'
$HostIP = if ($env:VPS_HOST) { $env:VPS_HOST } else { '104.194.140.203' }
$User = if ($env:VPS_USER) { $env:VPS_USER } else { 'Administrator' }
if (-not $env:VPS_PW) { throw 'Set VPS_PW in this terminal first (do not paste in chat)' }

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Zip = Join-Path $env:TEMP "bilshenz-godmode.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path @(
  (Join-Path $RepoRoot 'deploy\windows'),
  (Join-Path $RepoRoot 'backend'),
  (Join-Path $RepoRoot 'mt5_trading_system\python')
) -DestinationPath $Zip -Force

Write-Host "Testing SSH to $HostIP ..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 "${User}@${HostIP}" "hostname"
if ($LASTEXITCODE -ne 0) {
  throw @"
SSH failed. Fix in provider panel:
  - Allow TCP port 22 inbound (your IP or 0.0.0.0/0)
  - On VPS (one RDP login): run enable-remote-admin.ps1
Do NOT keep two RDP windows open.
"@
}

Write-Host "Uploading bundle (~$([math]::Round((Get-Item $Zip).Length/1MB,1)) MB)..."
scp -o StrictHostKeyChecking=no "${Zip}" "${User}@${HostIP}:C:/opt/bilshenz-godmode.zip"
scp -o StrictHostKeyChecking=no (Join-Path $RepoRoot 'deploy\windows\vps-full-install.ps1') "${User}@${HostIP}:C:/opt/vps-full-install.ps1"

$Remote = @'
powershell -NoProfile -ExecutionPolicy Bypass -Command "
  New-Item -ItemType Directory -Force -Path C:/opt | Out-Null;
  if (Test-Path C:/opt/bilshenz) { Remove-Item C:/opt/bilshenz -Recurse -Force };
  Expand-Archive -Force C:/opt/bilshenz-godmode.zip C:/opt/bilshenz-src;
  Move-Item C:/opt/bilshenz-src C:/opt/bilshenz;
  Copy-Item C:/opt/vps-full-install.ps1 C:/opt/bilshenz/deploy/windows/ -Force -ErrorAction SilentlyContinue;
  powershell -ExecutionPolicy Bypass -File C:/opt/vps-full-install.ps1
"
'@

Write-Host 'Running install on VPS (10-20 min). Do not open RDP until this finishes.'
ssh -o StrictHostKeyChecking=no "${User}@${HostIP}" $Remote

Write-Host 'Verifying...'
ssh -o StrictHostKeyChecking=no "${User}@${HostIP}" "powershell -Command `"Test-Path C:/opt/bilshenz; try { (Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 5).connected } catch { 'mt5-not-ready' }`""
Write-Host 'GODMODE deploy finished. Now RDP in ONCE: install MT5 Exness, login, XAUUSD.' -ForegroundColor Green
