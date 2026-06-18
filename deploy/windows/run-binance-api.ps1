param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$PyDir = Join-Path $AppDir 'binance_trading_system\python'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'binance-api.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null

Set-Location $PyDir
$py = Join-Path $PyDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  "$(Get-Date -Format o) ERROR: missing venv at $PyDir" *>> $Log
  exit 1
}

$env:PORT = if ($env:BINANCE_API_PORT) { $env:BINANCE_API_PORT } else { '8766' }
$env:HOST = if ($env:BINANCE_API_HOST) { $env:BINANCE_API_HOST } else { '127.0.0.1' }
if ($env:BROKER_MODE -eq 'binance' -and -not $env:BINANCE_API_HOST) {
  $env:HOST = '0.0.0.0'
}

& $py main.py *>> $Log
