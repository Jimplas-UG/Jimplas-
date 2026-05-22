# Bootstrap without Administrator (no OpenSSH, no scheduled tasks). Uses background jobs.
param([string]$AppDir = 'C:\opt\bilshenz')
$ErrorActionPreference = 'Stop'
$EnvDir = 'C:\ProgramData\Bilshenz'
$EnvFile = Join-Path $EnvDir 'tradingbot.env'
$LogDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $EnvDir, $LogDir | Out-Null

Push-Location (Join-Path $AppDir 'backend')
npm install 2>$null
npm run strategy:freeze 2>$null
Pop-Location

$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
if (-not (Test-Path (Join-Path $PyDir '.venv'))) {
  python -m venv (Join-Path $PyDir '.venv')
}
& (Join-Path $PyDir '.venv\Scripts\pip.exe') install -q -r (Join-Path $AppDir 'deploy\windows\requirements.txt')

if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $AppDir 'deploy\windows\tradingbot.env.example') $EnvFile
  $key = [guid]::NewGuid().ToString('N')
  (Get-Content $EnvFile) -replace 'change-me-long-random-secret', $key | Set-Content $EnvFile
  (Get-Content $EnvFile) -replace 'FORWARD_DRY_RUN=1', 'FORWARD_DRY_RUN=0' | Set-Content $EnvFile
}

& (Join-Path $AppDir 'deploy\windows\go-live.ps1') -AppDir $AppDir
Write-Host 'bootstrap-lite OK (non-admin mode)' -ForegroundColor Green
