# Run on VPS after repo is at C:\opt\bilshenz. No winget required.
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Win = Join-Path $App 'deploy\windows'
$EnvFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
New-Item -ItemType Directory -Force -Path C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

$runtimeScript = Join-Path $Win 'install-runtimes-no-winget.ps1'
if (Test-Path $runtimeScript) {
  & $runtimeScript
} else {
  throw 'Missing install-runtimes-no-winget.ps1 - re-download repo zip from GitHub'
}

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path', 'User')

Push-Location (Join-Path $App 'backend')
npm install
npm run strategy:freeze 2>$null
Pop-Location

$Py = Join-Path $App 'mt5_trading_system\python'
if (-not (Test-Path (Join-Path $Py '.venv'))) { python -m venv (Join-Path $Py '.venv') }
& (Join-Path $Py '.venv\Scripts\pip.exe') install -q fastapi uvicorn MetaTrader5 pydantic requests

if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $Win 'tradingbot.env.example') $EnvFile -ErrorAction SilentlyContinue
}
if (-not (Test-Path $EnvFile)) {
  @('STRATEGY_FREEZE=1','PRODUCTION_MODE=1','MT5_API_URL=http://127.0.0.1:8765','FORWARD_DRY_RUN=1','TRADINGBOT_LOG_DIR=C:\logs\tradingbot') | Set-Content $EnvFile
}

& (Join-Path $Win 'install-scheduled-tasks.ps1') -AppDir $App
& (Join-Path $Win 'install-log-rotation.ps1') -ErrorAction SilentlyContinue
& (Join-Path $Win 'start-bot.ps1')

$mt5 = 'C:\Program Files\MetaTrader 5 Exness'
if (Test-Path (Join-Path $mt5 'terminal64.exe')) {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) {
    Start-Process (Join-Path $mt5 'terminal64.exe')
    Start-Sleep 15
  }
}

Write-Host 'FINISH_SETUP_OK' -ForegroundColor Green
Write-Host 'Install Exness MT5 on VPS, login, XAUUSD, then:'
Write-Host '  Invoke-RestMethod http://127.0.0.1:8765/api/status'
pause
