# Phase 2 — Validate Python 3.11+ venv and MT5 bridge imports.
param([string]$AppDir = 'C:\opt\bilshenz')

$ErrorActionPreference = 'Stop'
Write-Host '=== Phase 2: Python environment ===' -ForegroundColor Cyan

$pyVer = python --version 2>&1
Write-Host "  $pyVer"
if ($pyVer -notmatch 'Python 3\.(1[1-9]|[2-9]\d)') {
  Write-Host 'FAIL: Need Python 3.11+ (winget install Python.Python.3.12)' -ForegroundColor Red
  exit 1
}

$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$VenvPy = Join-Path $PyDir '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
  Write-Host "FAIL: venv missing at $PyDir\.venv — run production-setup.ps1" -ForegroundColor Red
  exit 1
}

$test = @'
import sys
import fastapi
import uvicorn
import MetaTrader5 as mt5
print("imports_ok", sys.version.split()[0], "mt5", mt5.__version__)
'@
& $VenvPy -c $test
if ($LASTEXITCODE -ne 0) {
  Write-Host 'FAIL: import check failed — pip install -r deploy\windows\requirements.txt' -ForegroundColor Red
  exit 1
}

# Node (forward bot)
try {
  $nodeVer = node --version 2>&1
  Write-Host "  Node: $nodeVer"
} catch {
  Write-Host 'FAIL: Node.js not in PATH' -ForegroundColor Red
  exit 1
}

$backend = Join-Path $AppDir 'backend\node_modules'
if (-not (Test-Path $backend)) {
  Write-Host 'WARN: backend node_modules missing — run: cd backend && npm ci' -ForegroundColor Yellow
}

Write-Host 'PHASE2_OK' -ForegroundColor Green
