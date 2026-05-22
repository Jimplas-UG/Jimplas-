# Full deployment validation (Phases 1–7 smoke test). No secrets printed.
param([string]$AppDir = 'C:\opt\bilshenz')

$ErrorActionPreference = 'Continue'
$fail = 0

function Step([string]$label, [scriptblock]$fn) {
  Write-Host "`n>> $label" -ForegroundColor Cyan
  try {
    & $fn
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
    Write-Host "   OK" -ForegroundColor Green
  } catch {
    Write-Host "   FAIL: $_" -ForegroundColor Red
    $script:fail++
  }
}

Step 'Phase 1 system' {
  & (Join-Path $PSScriptRoot 'phase1-system-prep.ps1') -ValidateOnly
}

Step 'Phase 2 Python/Node' {
  & (Join-Path $PSScriptRoot 'validate-python-env.ps1') -AppDir $AppDir
}

Step 'Env file' {
  $ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
  if (-not (Test-Path $ef)) { throw "Missing $ef" }
  . (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
  if (-not $env:FORWARD_DRY_RUN) { throw 'FORWARD_DRY_RUN not set' }
}

Step 'Scheduled tasks' {
  @('Bilshenz-MT5-API', 'Bilshenz-DeskAPI', 'Bilshenz-ForwardBot', 'Bilshenz-Watchdog') | ForEach-Object {
    $t = Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue
    if (-not $t) { throw "$_ not registered" }
    Write-Host "   $_ : $($t.State)" -ForegroundColor DarkGray
  }
}

Step 'HTTP health' {
  & (Join-Path $PSScriptRoot 'health-check.ps1')
}

Step 'Phase 3 MT5 (if terminal up)' {
  $proc = Get-Process terminal64 -ErrorAction SilentlyContinue
  if ($proc) {
    & (Join-Path $PSScriptRoot 'validate-mt5.ps1') -AppDir $AppDir -WaitSec 20
  } else {
    Write-Host '   SKIP — start MT5 and re-run validate-mt5.ps1' -ForegroundColor Yellow
  }
}

Step 'Log files writable' {
  $dir = if ($env:TRADINGBOT_LOG_DIR) { $env:TRADINGBOT_LOG_DIR } else { 'C:\logs\tradingbot' }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $test = Join-Path $dir '.write-test'
  'ok' | Set-Content $test
  Remove-Item $test -Force
}

Write-Host ''
if ($fail -gt 0) {
  Write-Host "VALIDATION_FAILED ($fail step(s))" -ForegroundColor Red
  exit 1
}
Write-Host 'VALIDATION_OK — set FORWARD_DRY_RUN=0 only after demo checks pass' -ForegroundColor Green
