& (Join-Path $PSScriptRoot 'stop-bot.ps1')
Start-Sleep -Seconds 3
& (Join-Path $PSScriptRoot 'start-bot.ps1')
