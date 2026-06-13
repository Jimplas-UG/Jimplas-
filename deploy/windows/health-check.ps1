# Safe health check - never prints secrets.
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1') -ErrorAction SilentlyContinue
$LogDir = $env:TRADINGBOT_LOG_DIR
if (-not $LogDir) { $LogDir = 'C:\logs\tradingbot' }

Write-Host '=== Scheduled tasks ===' -ForegroundColor Cyan
@('Bilshenz-MT5-API', 'Bilshenz-Binance-API', 'Bilshenz-DeskAPI', 'Bilshenz-ForwardBot', 'Bilshenz-Watchdog') | ForEach-Object {
  $t = Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue
  if ($t) { Write-Host "$_ : $($t.State)" } else { Write-Host "$_ : NOT REGISTERED" -ForegroundColor Yellow }
}

Write-Host '=== HTTP health ===' -ForegroundColor Cyan
try {
  $desk = Invoke-RestMethod 'http://127.0.0.1:8791/health' -TimeoutSec 5
  Write-Host "desk-api: ok=$($desk.ok)"
} catch { Write-Host "desk-api: DOWN" -ForegroundColor Red }

$mt5Url = if ($env:MT5_API_URL) { $env:MT5_API_URL.TrimEnd('/') } else { 'http://127.0.0.1:8765' }
try {
  $mt5 = Invoke-RestMethod "$mt5Url/api/status" -TimeoutSec 8
  Write-Host "mt5-api: connected=$($mt5.connected) server=$($mt5.account.server)"
} catch { Write-Host "mt5-api: DOWN (is MT5 terminal logged in?)" -ForegroundColor Red }

$binanceUrl = if ($env:BINANCE_API_URL) { $env:BINANCE_API_URL.TrimEnd('/') } else { 'http://127.0.0.1:8766' }
try {
  $bn = Invoke-RestMethod "$binanceUrl/health" -TimeoutSec 8
  Write-Host "binance-api: ok=$($bn.ok) mode=$($bn.mode)"
} catch { Write-Host "binance-api: DOWN (npm run binance-api in backend?)" -ForegroundColor Yellow }

Write-Host '=== Safety ===' -ForegroundColor Cyan
$safety = Join-Path $LogDir 'safety-state.json'
if (Test-Path $safety) {
  $s = Get-Content $safety | ConvertFrom-Json
  Write-Host "failsafe=$($s.failsafe) apiFailures=$($s.consecutiveApiFailures)"
} else { Write-Host 'no safety-state yet' }

Write-Host '=== Config (non-secret) ===' -ForegroundColor Cyan
Write-Host "PRODUCTION_MODE=$($env:PRODUCTION_MODE) FORWARD_DRY_RUN=$($env:FORWARD_DRY_RUN) BROKER_MODE=$($env:BROKER_MODE)"
Write-Host "MAX_DAILY_LOSS_PCT=$($env:MAX_DAILY_LOSS_PCT) MAX_DAILY_TRADES=$($env:MAX_DAILY_TRADES)"
Write-Host "MT5_API_URL=$mt5Url BINANCE_API_URL=$binanceUrl"

Write-Host '=== Recent log lines ===' -ForegroundColor Cyan
$fb = Join-Path $LogDir 'forward-bot.log'
if (Test-Path $fb) { Get-Content $fb -Tail 5 }
