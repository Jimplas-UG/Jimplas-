param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$Backend = Join-Path $AppDir 'backend'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'watchdog.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null
Set-Location $Backend
npx tsx ..\deploy\watchdog.ts 2>&1 | Tee-Object -FilePath $Log -Append
