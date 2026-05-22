# Run on VPS after repo is at C:\opt\bilshenz. Skips broken production-setup.ps1 on disk.
# Paste or: powershell -ExecutionPolicy Bypass -File C:\opt\bilshenz\deploy\windows\vps-finish-setup.ps1
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$EnvFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
$LogDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $LogDir, 'C:\ProgramData\Bilshenz' | Out-Null

foreach ($id in @('Python.Python.3.12', 'OpenJS.NodeJS.LTS')) {
  winget install --id $id -e --accept-package-agreements --accept-source-agreements 2>$null
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

Push-Location (Join-Path $App 'backend')
npm install
npm run strategy:freeze 2>$null
Pop-Location

$Py = Join-Path $App 'mt5_trading_system\python'
if (-not (Test-Path (Join-Path $Py '.venv'))) { python -m venv (Join-Path $Py '.venv') }
& (Join-Path $Py '.venv\Scripts\pip.exe') install -q fastapi uvicorn MetaTrader5 pydantic requests

if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $App 'deploy\windows\tradingbot.env.example') $EnvFile -ErrorAction SilentlyContinue
}
if (-not (Test-Path $EnvFile)) {
  @('STRATEGY_FREEZE=1','PRODUCTION_MODE=1','MT5_API_URL=http://127.0.0.1:8765','FORWARD_DRY_RUN=1','TRADINGBOT_LOG_DIR=C:\logs\tradingbot') | Set-Content $EnvFile
}

$tasks = Join-Path $App 'deploy\windows\install-scheduled-tasks.ps1'
if (Test-Path $tasks) {
  & $tasks -AppDir $App
  & (Join-Path $App 'deploy\windows\install-log-rotation.ps1') -ErrorAction SilentlyContinue
  & (Join-Path $App 'deploy\windows\start-bot.ps1')
}

$mt5 = 'C:\Program Files\MetaTrader 5 Exness'
if (Test-Path (Join-Path $mt5 'terminal64.exe')) {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) { Start-Process (Join-Path $mt5 'terminal64.exe'); Start-Sleep 15 }
}

Write-Host 'FINISH_SETUP_OK' -ForegroundColor Green
Write-Host 'Login MT5 on VPS, add XAUUSD, then:'
Write-Host '  Invoke-RestMethod http://127.0.0.1:8765/api/status'
pause
