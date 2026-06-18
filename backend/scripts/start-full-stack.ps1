# Starts Binance Python bridge + desk-api for full BSV3.2 backend (Binance mode).
# Usage (from backend/):
#   npm run start:full
#   npm run start:full:paper
#
# Optional env before running:
#   $env:DESK_API_KEY = "your-secret"
#   $env:AUTH_JWT_SECRET = "your-auth-jwt-secret"
#   $env:AUTH_DEV_OTP = "1"
#   $env:BINANCE_API_KEY / BINANCE_API_SECRET / BINANCE_TESTNET=1

$ErrorActionPreference = 'Stop'
$BackendRoot = Split-Path $PSScriptRoot -Parent
$RepoRoot = Split-Path $BackendRoot -Parent
$BinanceDir = Join-Path $RepoRoot 'binance_trading_system\python'
$PortBinance = if ($env:PORT) { $env:PORT } else { '8766' }
$PortDesk = if ($env:DESK_API_PORT) { $env:DESK_API_PORT } else { '8791' }

if (-not (Test-Path (Join-Path $BinanceDir 'start-api.ps1'))) {
  Write-Error "Missing $BinanceDir\start-api.ps1"
}

Write-Host ''
Write-Host '=== BSV3.2 full backend (Binance + desk-api) ===' -ForegroundColor Cyan
Write-Host "Binance bridge -> http://127.0.0.1:$PortBinance"
Write-Host "Desk API       -> http://0.0.0.0:$PortDesk"
Write-Host ''

$env:BINANCE_API_URL = "http://127.0.0.1:$PortBinance"

# Start Binance bridge in background
$binanceJob = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $BinanceDir 'start-api.ps1')
) -WorkingDirectory $BinanceDir -PassThru -WindowStyle Minimized

Start-Sleep -Seconds 4

function Test-BinanceHealth {
  try {
    $r = Invoke-RestMethod "http://127.0.0.1:$PortBinance/health" -TimeoutSec 8
    return [bool]$r.ok
  } catch { return $false }
}

if (-not (Test-BinanceHealth)) {
  Write-Host 'WARN: Binance bridge not responding yet — desk-api will still start.' -ForegroundColor Yellow
  Write-Host '      Check binance_trading_system\python window for errors.' -ForegroundColor Yellow
} else {
  Write-Host 'OK: Binance bridge healthy' -ForegroundColor Green
}

Write-Host ''
Write-Host 'Starting desk-api (Ctrl+C stops desk-api only; close Binance window separately)...' -ForegroundColor Cyan
Write-Host ''

Set-Location $BackendRoot
try {
  npm run desk-api
} finally {
  if ($binanceJob -and -not $binanceJob.HasExited) {
    Write-Host 'Stopping Binance bridge...' -ForegroundColor DarkGray
    Stop-Process -Id $binanceJob.Id -Force -ErrorAction SilentlyContinue
  }
}
