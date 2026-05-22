# Emergency halt: stop bot, force dry-run, enable failsafe in safety state.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'stop-bot.ps1')

$envFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (Test-Path $envFile) {
  $content = Get-Content $envFile
  $updated = $content | ForEach-Object {
    if ($_ -match '^FORWARD_DRY_RUN=') { 'FORWARD_DRY_RUN=1' } else { $_ }
  }
  if ($updated -notmatch 'FORWARD_DRY_RUN=') { $updated += 'FORWARD_DRY_RUN=1' }
  Set-Content -Path $envFile -Value $updated -Encoding ASCII
}

$logDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$safetyPath = Join-Path $logDir 'safety-state.json'
$safety = @{
  nyDay = $null
  dayStartEquity = 0
  consecutiveApiFailures = 99
  failsafe = $true
  failsafeReason = 'emergency_halt.ps1'
  lastExecutedBarT = $null
  lastOrderIdempotencyKey = $null
}
$safety | ConvertTo-Json | Set-Content -Path $safetyPath -Encoding UTF8

$row = @{ ts = (Get-Date -Format 'o'); event = 'safety'; message = 'emergency_halt' } | ConvertTo-Json -Compress
Add-Content (Join-Path $logDir 'safety.jsonl') -Value $row

Write-Host 'EMERGENCY_HALT_OK - bot stopped, FORWARD_DRY_RUN=1, failsafe on' -ForegroundColor Red
Write-Host "Review: $safetyPath before clearing failsafe" -ForegroundColor Yellow
