# P0 repair: single-instance bot fleet, safe dry-run session, clear stale failsafe.
#Requires -RunAsAdministrator
param([string]$AppDir = 'C:\opt\bilshenz')
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$Win = Join-Path $AppDir 'deploy\windows'
$LogDir = 'C:\logs\tradingbot'
$EnvFile = 'C:\ProgramData\Bilshenz\tradingbot.env'

. (Join-Path $Win 'Import-TradingBotEnv.ps1')

Write-Host '=== Stop scheduled tasks ===' -ForegroundColor Cyan
& (Join-Path $Win 'stop-bot.ps1')

Write-Host '=== Kill orphan bilshenz node/python (keep terminal64) ===' -ForegroundColor Cyan
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'bilshenz|mt5_trading_system\\python'
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

Write-Host '=== Strategy freeze manifest ===' -ForegroundColor Cyan
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
Push-Location (Join-Path $AppDir 'backend')
npm run strategy:freeze 2>&1 | Out-Host
npm run strategy:verify 2>&1 | Out-Host
Pop-Location

Write-Host '=== Session + safety (dry-run, no failsafe) ===' -ForegroundColor Cyan
$sessionPath = Join-Path $AppDir 'backend\validation\data\forward-demo-session.json'
if (Test-Path $sessionPath) {
  $s = Get-Content $sessionPath -Raw | ConvertFrom-Json
  $s.dryRun = $true
  $utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($sessionPath, ($s | ConvertTo-Json -Depth 6), $utf8NoBom)
}
$safetyPath = Join-Path $LogDir 'safety-state.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$safetyJson = @{
  nyDay = $null
  dayStartEquity = 0
  peakEquity = 0
  consecutiveApiFailures = 0
  failsafe = $false
  failsafeReason = $null
  lastExecutedBarT = $null
  lastOrderIdempotencyKey = $null
} | ConvertTo-Json
[System.IO.File]::WriteAllText($safetyPath, $safetyJson, $utf8NoBom)

if (Test-Path $EnvFile) {
  $c = Get-Content $EnvFile
  if ($c -notmatch '^FORWARD_DRY_RUN=') { $c += 'FORWARD_DRY_RUN=1' }
  else { $c = $c | ForEach-Object { if ($_ -match '^FORWARD_DRY_RUN=') { 'FORWARD_DRY_RUN=1' } else { $_ } } }
  Set-Content $EnvFile -Value $c -Encoding ASCII
}

Write-Host '=== Start single fleet (scheduled tasks) ===' -ForegroundColor Cyan
& (Join-Path $Win 'start-bot.ps1')
Start-Sleep -Seconds 25
& (Join-Path $Win 'health-check.ps1')

Write-Host 'REPAIR_P0_DONE' -ForegroundColor Green
