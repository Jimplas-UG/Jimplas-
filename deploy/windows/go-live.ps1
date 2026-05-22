# End-to-end: env, deps, services, health. Run as Administrator when possible.
param(
  [string]$AppDir = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent),
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$EnvDir = 'C:\ProgramData\Bilshenz'
$EnvFile = Join-Path $EnvDir 'tradingbot.env'
$LogDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $EnvDir, $LogDir | Out-Null

# Secure API key (not printed)
$apiKey = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$dry = if ($DryRun) { '1' } else { '0' }
$mt5Path = 'C:\Program Files\MetaTrader 5 Exness'
if (-not (Test-Path $mt5Path)) { $mt5Path = 'C:\Program Files\MetaTrader 5' }

@(
  'STRATEGY_FREEZE=1',
  'PRODUCTION_MODE=1',
  'PRODUCTION_NO_EXPIRY=1',
  'DESK_API_PORT=8791',
  "DESK_API_KEY=$apiKey",
  'MT5_API_URL=http://127.0.0.1:8765',
  'MT5_SYMBOL=XAUUSD',
  "MT5_TERMINAL_PATH=$mt5Path",
  "FORWARD_DRY_RUN=$dry",
  'FORWARD_POLL_SEC=45',
  'RISK_PCT=0.005',
  'MAX_DAILY_LOSS_PCT=3',
  'MAX_DAILY_TRADES=3',
  'MAX_API_FAILURES=8',
  "TRADINGBOT_LOG_DIR=$LogDir",
  "SAFETY_STATE_PATH=$LogDir\safety-state.json",
  'TELEGRAM_BOT_TOKEN=',
  'TELEGRAM_CHAT_ID='
) | Set-Content -Path $EnvFile -Encoding ASCII
icacls $EnvFile /inheritance:r /grant:r "Administrators:F" "$env:USERNAME`:F" 2>$null | Out-Null

# MT5 terminal
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
  if (Test-Path (Join-Path $mt5Path 'terminal64.exe')) {
    Start-Process (Join-Path $mt5Path 'terminal64.exe')
    Start-Sleep -Seconds 20
  }
}

# Backend deps
Push-Location (Join-Path $AppDir 'backend')
npm install --silent 2>$null
npm run strategy:freeze 2>$null
Pop-Location

# Python MT5 API venv
$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$venvPy = Join-Path $PyDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  python -m venv (Join-Path $PyDir '.venv')
  & (Join-Path $PyDir '.venv\Scripts\pip.exe') install -q -r (Join-Path $AppDir 'deploy\windows\requirements.txt')
}

# Stop old jobs
Get-Job -Name Bilshenz* -ErrorAction SilentlyContinue | Stop-Job -EA SilentlyContinue
Get-Job -Name Bilshenz* -ErrorAction SilentlyContinue | Remove-Job -Force -EA SilentlyContinue

. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')

# Start MT5 API if down
try {
  $st = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 4
  if (-not $st.connected) { throw 'not connected' }
} catch {
  Start-Job -Name BilshenzMt5Api -ScriptBlock {
    Set-Location $using:PyDir
    $env:MT5_TERMINAL_PATH = $using:mt5Path
    $env:PORT = '8765'
    & $using:venvPy main.py
  } | Out-Null
  $ok = $false
  1..30 | ForEach-Object {
    Start-Sleep -Seconds 2
    try {
      $st = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 5
      if ($st.connected) { $ok = $true }
    } catch {}
    if ($ok) { return }
  }
  if (-not $ok) {
    Write-Host 'MT5 API not connected yet — start Exness MT5, log in, then run: .\deploy\windows\start-trading-now.ps1' -ForegroundColor Yellow
    return
  }
}

$WinDeploy = $PSScriptRoot
foreach ($svc in @(
  @{ Name = 'BilshenzDesk'; Script = 'run-desk-api.ps1' },
  @{ Name = 'BilshenzForward'; Script = 'run-forward-bot.ps1' },
  @{ Name = 'BilshenzWatch'; Script = 'run-watchdog.ps1' }
)) {
  $scriptPath = Join-Path $WinDeploy $svc.Script
  $ad = $AppDir
  Start-Job -Name $svc.Name -ScriptBlock {
    param($sp, $dir)
    & $sp -AppDir $dir
  } -ArgumentList $scriptPath, $ad | Out-Null
}

Start-Sleep -Seconds 6
& (Join-Path $PSScriptRoot 'health-check.ps1')
