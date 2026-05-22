# Paste on VPS (Administrator PowerShell) when deploy\windows is missing or MT5 API is down.
Set-ExecutionPolicy Bypass -Scope Process -Force
$App = 'C:\opt\bilshenz'
$Log = 'C:\opt\vps-repair.log'
function L($m) { "$(Get-Date -Format o) $m" | Tee-Object $Log -Append; Write-Host $m }

L '=== repair start ==='
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

# --- diagnose ---
L "bilshenz exists: $(Test-Path $App)"
if (Test-Path $App) {
  Get-ChildItem $App -Name | Select-Object -First 20 | ForEach-Object { L "  $_" }
  L "deploy/windows: $(Test-Path '$App\deploy\windows')"
  L "backend: $(Test-Path '$App\backend\package.json')"
  L "mt5 python: $(Test-Path '$App\mt5_trading_system\python\main.py')"
}

# --- git / tools ---
if (-not (Get-Command git -EA SilentlyContinue)) {
  winget install Git.Git -e --accept-package-agreements --accept-source-agreements
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
if (-not (Test-Path $App)) {
  L 'cloning repo...'
  git clone $Repo $App
} else {
  Push-Location $App
  if (Test-Path .git) { git pull 2>>$Log } else { L 'WARN: folder exists but not a git repo' }
  Pop-Location
}

if (-not (Test-Path "$App\backend\package.json")) {
  L 'FATAL: backend missing after clone — check internet and repo URL'
  exit 1
}

if (-not (Get-Command node -EA SilentlyContinue)) {
  winget install OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
if (-not (Get-Command python -EA SilentlyContinue)) {
  winget install Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}

Push-Location "$App\backend"
npm install 2>>$Log
npm run strategy:freeze 2>>$Log
Pop-Location

$Py = "$App\mt5_trading_system\python"
if (-not (Test-Path "$Py\main.py")) {
  L 'FATAL: mt5_trading_system/python missing'
  exit 1
}
if (-not (Test-Path "$Py\.venv")) { python -m venv "$Py\.venv" }
& "$Py\.venv\Scripts\pip.exe" install -q fastapi "uvicorn[standard]" MetaTrader5 pydantic requests 2>>$Log

$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (-not (Test-Path $ef)) {
  @(
    'STRATEGY_FREEZE=1','PRODUCTION_MODE=1','PRODUCTION_NO_EXPIRY=1','DESK_API_PORT=8791',
    "DESK_API_KEY=$([guid]::NewGuid().ToString('N'))",
    'MT5_API_URL=http://127.0.0.1:8765','MT5_SYMBOL=XAUUSD',
    'MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 Exness',
    'FORWARD_DRY_RUN=1','FORWARD_POLL_SEC=45','RISK_PCT=0.005',
    'MAX_DAILY_LOSS_PCT=3','MAX_DAILY_TRADES=3','MAX_API_FAILURES=8',
    'TRADINGBOT_LOG_DIR=C:\logs\tradingbot','SAFETY_STATE_PATH=C:\logs\tradingbot\safety-state.json'
  ) | Set-Content $ef
}

# Stop stale bot processes
Get-Process python, node -EA SilentlyContinue | Where-Object { $_.Path -match 'bilshenz|mt5_trading' } | Stop-Process -Force -EA SilentlyContinue
Start-Sleep -Seconds 2

$mt5Path = 'C:\Program Files\MetaTrader 5 Exness'
if (-not (Test-Path "$mt5Path\terminal64.exe")) { $mt5Path = 'C:\Program Files\MetaTrader 5' }

# Start MT5 terminal if installed
if (Test-Path "$mt5Path\terminal64.exe") {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) {
    L 'Starting MT5 terminal...'
    Start-Process "$mt5Path\terminal64.exe"
    Start-Sleep -Seconds 15
  }
} else {
  L 'WARN: MT5 not installed — install Exness MT5, login, XAUUSD, then re-run this script'
}

# Start MT5 API (always — does not need deploy\windows)
L 'Starting MT5 API on :8765...'
Start-Process powershell -WindowStyle Minimized -ArgumentList @(
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command',
  @"
Set-Location '$Py'
`$env:MT5_TERMINAL_PATH='$mt5Path'
`$env:PORT='8765'
& '$Py\.venv\Scripts\python.exe' main.py 2>> 'C:\logs\tradingbot\mt5-api-error.log'
"@
)

$ready = $false
1..25 | ForEach-Object {
  Start-Sleep -Seconds 2
  try {
    $st = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 4
    L "MT5 API health: $($st | ConvertTo-Json -Compress)"
    $ready = $true
    break
  } catch {}
}
if (-not $ready) { L 'WARN: port 8765 not up yet — wait 30s and run: Invoke-RestMethod http://127.0.0.1:8765/api/status' }

# Forward bot + desk (optional if deploy exists)
$Win = "$App\deploy\windows"
if (Test-Path "$Win\install-scheduled-tasks.ps1") {
  L 'Registering scheduled tasks...'
  & "$Win\install-scheduled-tasks.ps1" -AppDir $App
  & "$Win\start-bot.ps1"
} else {
  L 'deploy\windows not in repo — starting forward bot manually'
  Start-Process powershell -WindowStyle Minimized -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command',
    @"
Set-Location '$App\backend'
Get-Content '$ef' | ForEach-Object {
  if (`$_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1],`$matches[2],'Process') }
}
`$env:STRATEGY_FREEZE='1'; `$env:PRODUCTION_MODE='1'
npx tsx scripts/run-forward-demo-30d.ts 2>> 'C:\logs\tradingbot\forward-bot.log'
"@
  )
}

L '=== status ==='
try { Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 6 | Format-List } catch { L "api/status: $_" }
try { Invoke-RestMethod 'http://127.0.0.1:8791/health' -TimeoutSec 4 } catch { L 'desk-api: not started (optional)' }
L "Log: $Log"
Write-Host 'REPAIR_DONE' -ForegroundColor Green
