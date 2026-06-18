# Validates Binance Python bridge venv and optional smoke test.
param([string]$AppDir = 'C:\opt\bilshenz')
$ErrorActionPreference = 'Stop'
$BnDir = Join-Path $AppDir 'binance_trading_system\python'
$py = Join-Path $BnDir '.venv\Scripts\python.exe'

Write-Host '=== Binance Python env ===' -ForegroundColor Cyan
if (-not (Test-Path $py)) {
  Write-Host "FAIL: missing venv at $BnDir" -ForegroundColor Red
  exit 1
}
& $py -c "import fastapi, uvicorn; print('imports ok')"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host '=== Smoke (optional) ===' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'smoke-binance-bridge.ps1')
exit $LASTEXITCODE
