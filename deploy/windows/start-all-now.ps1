# Start MT5 API + desk-api + forward bot + watchdog (no scheduled tasks). VPS Administrator.
param([string]$AppDir = 'C:\opt\bilshenz')
Set-ExecutionPolicy Bypass -Scope Process -Force
$Win = Join-Path $AppDir 'deploy\windows'
$LogDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $LogDir, 'C:\ProgramData\Bilshenz' | Out-Null

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path', 'User')

$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (-not (Test-Path $ef)) {
  Copy-Item (Join-Path $Win 'tradingbot.env.example') $ef
  (Get-Content $ef) -replace 'change-me-long-random-secret', ([guid]::NewGuid().ToString('N')) | Set-Content $ef -Encoding ASCII
}
. (Join-Path $Win 'Import-TradingBotEnv.ps1')

function Test-PortListen([int]$Port) {
  $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host '=== Ports before ===' -ForegroundColor Cyan
Write-Host ('8765: ' + (Test-PortListen 8765))
Write-Host ('8791: ' + (Test-PortListen 8791))

# Stop stale
Get-Process python, node -EA SilentlyContinue | Where-Object {
  $_.Path -match 'bilshenz|mt5_trading_system'
} | Stop-Process -Force -EA SilentlyContinue
Start-Sleep 2

$Py = Join-Path $AppDir 'mt5_trading_system\python'
$pyexe = Join-Path $Py '.venv\Scripts\python.exe'
if (-not (Test-Path $pyexe)) {
  Write-Host 'FAIL: missing ' $pyexe -ForegroundColor Red
  exit 1
}

$mt5 = $env:MT5_TERMINAL_PATH
if (-not $mt5) { $mt5 = 'C:\Program Files\MetaTrader 5 Exness' }
if (Test-Path (Join-Path $mt5 'terminal64.exe')) {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) {
    Start-Process (Join-Path $mt5 'terminal64.exe')
    Start-Sleep 15
  }
}

if (-not (Test-PortListen 8765)) {
  Write-Host 'Starting MT5 API...' -ForegroundColor Cyan
  $c1 = "cd '$Py'; `$env:PORT='8765'; `$env:MT5_TERMINAL_PATH='$mt5'; & '$pyexe' main.py"
  Start-Process powershell -WindowStyle Normal -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $c1
}

$backend = Join-Path $AppDir 'backend'
if (-not (Test-Path (Join-Path $backend 'node_modules\tsx'))) {
  Write-Host 'npm install backend...' -ForegroundColor Cyan
  Push-Location $backend
  npm install
  Pop-Location
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host 'FAIL: npm not in PATH - install Node.js first' -ForegroundColor Red
  exit 1
}

if (-not (Test-PortListen 8791)) {
  Write-Host 'Starting desk-api...' -ForegroundColor Cyan
  $c2 = @"
cd '$backend'
`$env:STRATEGY_FREEZE='1'
`$env:DESK_API_PORT='8791'
Get-Content '$ef' | ForEach-Object { if (`$_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1],`$matches[2],'Process') } }
npx tsx src/server.ts
"@
  Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $c2
}

Write-Host 'Starting forward bot + watchdog...' -ForegroundColor Cyan
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Win 'run-forward-bot.ps1'), '-AppDir', $AppDir
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Win 'run-watchdog.ps1'), '-AppDir', $AppDir

Write-Host 'Waiting 20s...' -ForegroundColor DarkGray
Start-Sleep 20

& (Join-Path $Win 'health-check.ps1')
Write-Host 'START_ALL_NOW_DONE' -ForegroundColor Green
