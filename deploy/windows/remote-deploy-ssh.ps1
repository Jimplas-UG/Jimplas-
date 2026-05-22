# Remote deploy when OpenSSH is enabled on Windows VPS.
# Usage (local): $env:VPS_HOST='...'; $env:VPS_USER='Administrator'; $env:VPS_PW='...'; .\remote-deploy-ssh.ps1
param([string]$Host = $env:VPS_HOST, [string]$User = $env:VPS_USER, [int]$Port = 22)
$ErrorActionPreference = 'Stop'
if (-not $env:VPS_PW) { throw 'Set VPS_PW (do not commit to git)' }
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Archive = Join-Path $env:TEMP "bilshenz-deploy-$(Get-Date -Format 'yyyyMMddHHmmss').zip"
if (Test-Path $Archive) { Remove-Item $Archive -Force }
Compress-Archive -Path @(
  (Join-Path $RepoRoot 'deploy'),
  (Join-Path $RepoRoot 'backend'),
  (Join-Path $RepoRoot 'mt5_trading_system'),
  (Join-Path $RepoRoot 'backend\package.json'),
  (Join-Path $RepoRoot 'backend\package-lock.json')
) -DestinationPath $Archive -Force
$remote = "${User}@${Host}"
scp -P $Port -o StrictHostKeyChecking=no $Archive "${remote}:C:/opt/bilshenz-deploy.zip"
ssh -p $Port -o StrictHostKeyChecking=no $remote @"
powershell -NoProfile -ExecutionPolicy Bypass -Command \"
  Expand-Archive -Force C:/opt/bilshenz-deploy.zip C:/opt/bilshenz-src;
  Copy-Item -Recurse -Force C:/opt/bilshenz-src/deploy C:/opt/bilshenz/deploy;
  Copy-Item -Recurse -Force C:/opt/bilshenz-src/backend C:/opt/bilshenz/backend;
  Copy-Item -Recurse -Force C:/opt/bilshenz-src/mt5_trading_system C:/opt/bilshenz/mt5_trading_system;
  & C:/opt/bilshenz/deploy/windows/production-setup.ps1 -AppDir C:/opt/bilshenz
\"
"@
