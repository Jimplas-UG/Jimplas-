# Full APK pipeline debug — run from repo root or deploy/scripts/
param([string]$VpsHost = '157.245.33.42')
$ErrorActionPreference = 'Continue'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $repo 'frontend'))) { $repo = Split-Path $PSScriptRoot -Parent }
$fail = 0

function Step($name, [scriptblock]$fn) {
  Write-Host "`n=== $name ===" -ForegroundColor Cyan
  try {
    & $fn
    Write-Host "PASS $name" -ForegroundColor Green
  } catch {
    Write-Host "FAIL $name - $($_.Exception.Message)" -ForegroundColor Red
    $script:fail++
  }
}

Step 'VPS binance health' {
  $r = Invoke-RestMethod "http://${VpsHost}:8766/health" -TimeoutSec 15
  if (-not $r.ok) { throw 'not ok' }
  Write-Host "  mode=$($r.mode) connected=$($r.connected)"
}

Step 'VPS desk health' {
  $r = Invoke-RestMethod "http://${VpsHost}:8791/health" -TimeoutSec 15
  if (-not $r.ok) { throw 'not ok' }
}

Step 'VPS APK download route' {
  $r = Invoke-RestMethod "http://${VpsHost}:8791/download" -TimeoutSec 15
  if ($r.error -eq 'unauthorized') {
    throw 'Route needs auth. Run VPS-PASTE-FIX-APK.sh on VPS.'
  }
  if ($r.ok -eq $true) {
    Write-Host "  apk size=$($r.sizeBytes) bytes"
  } elseif ($r.error -eq 'apk_not_found') {
    Write-Host '  route OK, APK file missing on VPS' -ForegroundColor Yellow
  } else {
    throw "unexpected response"
  }
}

Step 'Local release verify' {
  Push-Location (Join-Path $repo 'frontend')
  $env:EXPO_PUBLIC_DESK_API_URL = "http://${VpsHost}:8791"
  $env:EXPO_PUBLIC_BINANCE_API_URL = "http://${VpsHost}:8791/v1/binance"
  $env:EXPO_PUBLIC_DESK_API_KEY = 'debug-check'
  $env:EAS_BUILD = 'true'
  $env:BABEL_ENV = 'production'
  $env:SKIP_GIT_CHECK = '1'
  node scripts/verify-release-build.js 2>&1 | ForEach-Object { Write-Host "  $_" }
  if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
  Pop-Location
}

Step 'EAS CLI' {
  $easCmd = $null
  if (Get-Command eas -ErrorAction SilentlyContinue) { $easCmd = 'eas' }
  else {
    $local = Join-Path $repo 'frontend\.tools-eas\node_modules\.bin\eas.cmd'
    if (Test-Path $local) { $easCmd = $local }
  }
  if (-not $easCmd) { throw 'eas not installed. Run: npm install -g eas-cli then eas login' }
  & $easCmd whoami 2>&1 | ForEach-Object { Write-Host "  $_" }
  if ($LASTEXITCODE -ne 0) { throw 'eas whoami failed - run eas login' }
}

Step 'SSH to VPS' {
  ssh -o BatchMode=yes -o ConnectTimeout=8 "root@${VpsHost}" "echo ok" 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw 'SSH key not authorized from this PC. Use Cursor Remote SSH for VPS commands.'
  }
}

Write-Host "`n========================================" -ForegroundColor Cyan
if ($fail -gt 0) {
  Write-Host "DEBUG_FAILED: $fail check(s)" -ForegroundColor Red
  Write-Host "Fix VPS: bash /opt/bilshenz/deploy/ubuntu/VPS-PASTE-FIX-APK.sh" -ForegroundColor Yellow
  exit 1
}
Write-Host 'DEBUG_OK' -ForegroundColor Green
Write-Host "Install URL: http://${VpsHost}:8791/download/bilshenz.apk"
