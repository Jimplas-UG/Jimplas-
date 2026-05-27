param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$Backend = Join-Path $AppDir 'backend'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'desk-api.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null
Set-Location $Backend
npx tsx src/server.ts 2>&1 | ForEach-Object { $_ | Out-File -FilePath $Log -Append -Encoding utf8; $_ }
