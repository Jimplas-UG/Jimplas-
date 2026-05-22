# Self-contained VPS install (paste entire file in Administrator PowerShell on 104.194.140.203)
Set-ExecutionPolicy Bypass -Scope Process -Force
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
New-Item -ItemType Directory -Force -Path C:\opt, 'C:\logs\tradingbot', 'C:\ProgramData\Bilshenz' | Out-Null
if (-not (Test-Path "$App\.git")) { git clone $Repo $App }
Set-Location $App
git pull 2>$null
# Node
winget install OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements 2>$null
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
Push-Location "$App\backend"; npm install; npm run strategy:freeze 2>$null; Pop-Location
# Python MT5 venv
$Py = "$App\mt5_trading_system\python"
if (-not (Test-Path "$Py\.venv")) { python -m venv "$Py\.venv" }
& "$Py\.venv\Scripts\pip.exe" install -q fastapi uvicorn MetaTrader5 pydantic requests
# Env
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
Write-Host 'Install OK. Next: open MT5 Exness, login, then run scheduled-task install from repo deploy\windows if present.'
