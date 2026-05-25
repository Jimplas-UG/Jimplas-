param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'mt5-api.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null
Set-Location $PyDir
$env:PORT = '8765'
$py = Join-Path $PyDir '.venv\Scripts\python.exe'
& $py main.py *>> $Log
