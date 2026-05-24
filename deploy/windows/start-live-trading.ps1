# Enable live forward trading (FORWARD_DRY_RUN=0) and clean-restart fleet.
#Requires -RunAsAdministrator
param([string]$AppDir = 'C:\opt\bilshenz')
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$Win = Join-Path $AppDir 'deploy\windows'
$EnvFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
$SessionPath = Join-Path $AppDir 'backend\validation\data\forward-demo-session.json'
$SafetyPath = 'C:\logs\tradingbot\safety-state.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

Write-Host '=== Pre-flight MT5 ===' -ForegroundColor Cyan
$st = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 10
if (-not $st.connected) { throw 'MT5 not connected — log into Exness MT5 first.' }
Write-Host ("MT5 OK login={0} equity={1} trade_allowed={2}" -f $st.account.login, $st.account.equity, $st.account.trade_allowed) -ForegroundColor Green

Write-Host '=== Enable LIVE (FORWARD_DRY_RUN=0) ===' -ForegroundColor Cyan
$lines = Get-Content $EnvFile | Where-Object { $_ -notmatch '^FORWARD_DRY_RUN=' }
$lines += 'FORWARD_DRY_RUN=0'
Set-Content $EnvFile -Value $lines -Encoding ASCII

if (Test-Path $SessionPath) {
  $s = Get-Content $SessionPath -Raw | ConvertFrom-Json
  $s.dryRun = $false
  [System.IO.File]::WriteAllText($SessionPath, ($s | ConvertTo-Json -Depth 6), $utf8NoBom)
}

$safety = @{
  nyDay               = $null
  dayStartEquity      = [double]$st.account.equity
  peakEquity          = [double]$st.account.equity
  consecutiveApiFailures = 0
  failsafe            = $false
  failsafeReason      = $null
  lastExecutedBarT    = $null
  lastOrderIdempotencyKey = $null
} | ConvertTo-Json
[System.IO.File]::WriteAllText($SafetyPath, $safety, $utf8NoBom)

Write-Host '=== Strategy freeze + verify ===' -ForegroundColor Cyan
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
Push-Location (Join-Path $AppDir 'backend')
npm run strategy:freeze 2>&1 | Out-Host
npm run strategy:verify 2>&1 | Out-Host
Pop-Location

Write-Host '=== Clean restart fleet ===' -ForegroundColor Cyan
& (Join-Path $Win 'stop-bot.ps1')
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'bilshenz|mt5_trading_system\\python'
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 4
& (Join-Path $Win 'start-bot.ps1')
Start-Sleep -Seconds 30
& (Join-Path $Win 'health-check.ps1')
Write-Host 'LIVE_TRADING_STARTED' -ForegroundColor Green
