# Paste ALL of this in VPS Administrator PowerShell - NO \\tsclient\ needed
Set-ExecutionPolicy Bypass -Scope Process -Force
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
$Log = 'C:\opt\vps-install.log'
function L($m) { "$(Get-Date -Format o) $m" | Tee-Object $Log -Append }
L 'start'
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

# Git
if (-not (Get-Command git -EA SilentlyContinue)) {
  winget install Git.Git -e --accept-package-agreements --accept-source-agreements
}
if (-not (Test-Path "$App\.git")) { git clone --depth 1 --branch main $Repo $App 2>>$Log }
Set-Location $App; git pull 2>>$Log
if (-not (Test-Path "$App\deploy\windows\production-setup.ps1")) {
  L 'ERROR: deploy/windows missing on GitHub - run: git push origin main from dev PC'
  throw 'Clone incomplete: deploy/windows not in repo'
}

# Node + Python
winget install OpenJS.NodeJS.LTS Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements 2>>$Log
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

Push-Location "$App\backend"
npm install 2>>$Log
npm run strategy:freeze 2>>$Log
Pop-Location

$Py = "$App\mt5_trading_system\python"
if (-not (Test-Path "$Py\.venv")) { python -m venv "$Py\.venv" }
& "$Py\.venv\Scripts\pip.exe" install -q fastapi "uvicorn[standard]" MetaTrader5 pydantic requests 2>>$Log

# Env (VPS-local MT5 only)
$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
@(
  'STRATEGY_FREEZE=1','PRODUCTION_MODE=1','PRODUCTION_NO_EXPIRY=1','DESK_API_PORT=8791',
  "DESK_API_KEY=$([guid]::NewGuid().ToString('N'))",
  'MT5_API_URL=http://127.0.0.1:8765','MT5_SYMBOL=XAUUSD',
  'MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 Exness',
  'FORWARD_DRY_RUN=1','FORWARD_POLL_SEC=45','RISK_PCT=0.005',
  'MAX_DAILY_LOSS_PCT=3','MAX_DAILY_TRADES=3','MAX_API_FAILURES=8',
  'TRADINGBOT_LOG_DIR=C:\logs\tradingbot','SAFETY_STATE_PATH=C:\logs\tradingbot\safety-state.json'
) | Set-Content $ef

# Scheduled tasks (24/7) - only if deploy\windows exists from git
$Win = "$App\deploy\windows"
if (Test-Path "$Win\install-scheduled-tasks.ps1") {
  & "$Win\install-scheduled-tasks.ps1" -AppDir $App
  & "$Win\install-log-rotation.ps1" -ErrorAction SilentlyContinue
  & "$Win\start-bot.ps1"
  L 'scheduled tasks OK'
} else {
  L 'deploy/windows missing from git - run vps-repair-and-start.ps1 or manual start below'
  Start-Process powershell -WindowStyle Minimized -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$Py'; `$env:MT5_TERMINAL_PATH='C:\Program Files\MetaTrader 5 Exness'; `$env:PORT='8765'; & '$Py\.venv\Scripts\python.exe' main.py"
  )
  Start-Sleep -Seconds 8
  Start-Process powershell -WindowStyle Minimized -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$App\backend'; `$env:STRATEGY_FREEZE='1'; `$env:PRODUCTION_MODE='1'; Get-Content 'C:\ProgramData\Bilshenz\tradingbot.env' | ForEach-Object { if (`$_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1],`$matches[2],'Process') } }; npx tsx scripts/run-forward-demo-30d.ts"
  )
}

L 'done - open MT5 Exness on THIS VPS, login, XAUUSD, then:'
Write-Host '1) Install Exness MT5 on VPS if not installed' -ForegroundColor Yellow
Write-Host '2) Login to Exness in MT5 on VPS' -ForegroundColor Yellow
Write-Host '3) curl http://127.0.0.1:8765/api/status  (connected should be true)' -ForegroundColor Yellow
Write-Host '4) Set FORWARD_DRY_RUN=0 in C:\ProgramData\Bilshenz\tradingbot.env and restart tasks' -ForegroundColor Yellow
Write-Host "Log: $Log" -ForegroundColor Green
