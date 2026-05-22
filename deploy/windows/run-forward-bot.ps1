param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$Backend = Join-Path $AppDir 'backend'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'forward-bot.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null
Set-Location $Backend
$env:PRODUCTION_MODE = '1'
$env:PRODUCTION_NO_EXPIRY = '1'
npx tsx scripts/run-forward-demo-30d.ts 2>&1 | Tee-Object -FilePath $Log -Append
