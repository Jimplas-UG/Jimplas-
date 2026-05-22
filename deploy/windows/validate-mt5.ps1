# Phase 3 — Validate MT5 terminal + Python bridge handshake (no secrets).
param(
  [string]$AppDir = 'C:\opt\bilshenz',
  [int]$WaitSec = 30
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1') -ErrorAction SilentlyContinue

$mt5Path = $env:MT5_TERMINAL_PATH
if (-not $mt5Path) { $mt5Path = 'C:\Program Files\MetaTrader 5 Exness' }
$terminal = Join-Path $mt5Path 'terminal64.exe'

Write-Host '=== Phase 3: MT5 validation ===' -ForegroundColor Cyan

if (-not (Test-Path $terminal)) {
  Write-Host "FAIL: terminal64.exe not found at $terminal" -ForegroundColor Red
  Write-Host 'Install: cd C:\opt\bilshenz\mt5_trading_system && .\install-mt5-broker.ps1 -Broker Exness' -ForegroundColor Yellow
  exit 1
}
Write-Host "  Terminal: $terminal" -ForegroundColor DarkGray

$proc = Get-Process terminal64 -ErrorAction SilentlyContinue
if (-not $proc) {
  Write-Host '  Starting MT5 (log in manually if prompted)...' -ForegroundColor Yellow
  Start-Process $terminal
  Start-Sleep -Seconds 15
} else {
  Write-Host '  MT5 process running' -ForegroundColor DarkGray
}

$mt5Url = if ($env:MT5_API_URL) { $env:MT5_API_URL.TrimEnd('/') } else { 'http://127.0.0.1:8765' }
$connected = $false
$deadline = (Get-Date).AddSeconds($WaitSec)

while ((Get-Date) -lt $deadline) {
  try {
    $st = Invoke-RestMethod "$mt5Url/api/status" -TimeoutSec 6
    Write-Host "  API: connected=$($st.connected) server=$($st.account.server) symbol check pending" -ForegroundColor DarkGray
    if ($st.connected) {
      $connected = $true
      break
    }
  } catch {
    Write-Host '  Waiting for mt5-api + logged-in terminal...' -ForegroundColor DarkGray
  }
  Start-Sleep -Seconds 3
}

if (-not $connected) {
  Write-Host 'FAIL: MT5 API not connected.' -ForegroundColor Red
  Write-Host @'
Fix checklist:
  1) Open MT5 → File → Login to trade account (correct server name)
  2) Market Watch → add XAUUSD → open chart (confirm ticks)
  3) Start API: .\deploy\windows\run-mt5-api.ps1  OR  .\start-bot.ps1
  4) Server mismatch? Use broker demo server from MT5 login dialog
'@ -ForegroundColor Yellow
  exit 1
}

try {
  $sym = Invoke-RestMethod "$mt5Url/api/symbol/XAUUSD" -TimeoutSec 8 -ErrorAction Stop
  Write-Host "  XAUUSD: bid=$($sym.bid) ask=$($sym.ask)" -ForegroundColor Green
} catch {
  Write-Host 'WARN: XAUUSD symbol query failed — add symbol in Market Watch' -ForegroundColor Yellow
}

Write-Host 'PHASE3_OK' -ForegroundColor Green
