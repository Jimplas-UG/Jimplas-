param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$Backend = Join-Path $AppDir 'backend'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'watchdog.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null
Set-Location $Backend
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
npx tsx ..\deploy\watchdog.ts 2>&1 | ForEach-Object { $_ | Out-File -FilePath $Log -Append -Encoding utf8; $_ }
