# Start MT5 Python API on port 8765 (manual). Run on VPS Administrator PowerShell.
param([string]$AppDir = 'C:\opt\bilshenz')

Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Continue'

Write-Host '=== MT5 API diagnostics ===' -ForegroundColor Cyan
$port = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($port) { Write-Host 'Port 8765 already listening' -ForegroundColor Green } else { Write-Host 'Port 8765 NOT listening' -ForegroundColor Yellow }

$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$py = Join-Path $PyDir '.venv\Scripts\python.exe'
Write-Host ('venv python: ' + (Test-Path $py))
Write-Host ('main.py: ' + (Test-Path (Join-Path $PyDir 'main.py')))

$LogDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:TRADINGBOT_LOG_DIR = $LogDir
$env:PORT = '8765'

$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (Test-Path $ef) {
  . (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1') -ErrorAction SilentlyContinue
} else {
  $env:MT5_TERMINAL_PATH = 'C:\Program Files\MetaTrader 5 Exness'
}

if (-not (Test-Path $py)) {
  Write-Host 'FAIL: run install-runtimes-no-winget.ps1 and venv setup first' -ForegroundColor Red
  exit 1
}

Get-Process python -EA SilentlyContinue | Where-Object { $_.Path -like '*bilshenz*' -or $_.CommandLine -like '*main.py*' } | Stop-Process -Force -EA SilentlyContinue
Start-Sleep 2

$mt5 = $env:MT5_TERMINAL_PATH
if (-not $mt5) { $mt5 = 'C:\Program Files\MetaTrader 5 Exness' }
if (Test-Path (Join-Path $mt5 'terminal64.exe')) {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) {
    Write-Host 'Starting MT5 terminal...' -ForegroundColor Cyan
    Start-Process (Join-Path $mt5 'terminal64.exe')
    Start-Sleep 15
  }
} else {
  Write-Host 'WARN: MT5 not installed at ' $mt5 -ForegroundColor Yellow
}

Write-Host 'Starting MT5 API (minimized window)...' -ForegroundColor Cyan
$cmd = "Set-Location '$PyDir'; `$env:PORT='8765'; `$env:MT5_TERMINAL_PATH='$mt5'; & '$py' main.py"
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd

$ok = $false
1..20 | ForEach-Object {
  Start-Sleep -Seconds 2
  try {
    $h = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 3
    Write-Host ('health: ' + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
    $ok = $true
    return
  } catch { Write-Host ('wait ' + $_) }
}
if (-not $ok) {
  Write-Host 'API did not start - check:' -ForegroundColor Red
  Write-Host ('  ' + (Join-Path $LogDir 'mt5-api-error.log'))
  if (Test-Path (Join-Path $LogDir 'mt5-api-error.log')) { Get-Content (Join-Path $LogDir 'mt5-api-error.log') -Tail 15 }
  exit 1
}
try {
  Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 5 | Format-List
} catch { Write-Host 'status: login to MT5 on VPS first' -ForegroundColor Yellow }
Write-Host 'MT5_API_STARTED' -ForegroundColor Green
