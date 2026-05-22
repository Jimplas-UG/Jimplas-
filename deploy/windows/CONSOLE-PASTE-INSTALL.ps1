# Paste in HOSTING WEB CONSOLE only (not RDP). Avoids RDP disconnect loop.
# Provider panel -> VPS -> Console / VNC / View console
Set-ExecutionPolicy Bypass -Scope Process -Force
$App = 'C:\opt\bilshenz'
New-Item -ItemType Directory -Force -Path C:\opt,'C:\logs\tradingbot','C:\ProgramData\Bilshenz' | Out-Null
# OpenSSH
Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | ForEach-Object {
  if ($_.State -ne 'Installed') { Add-WindowsCapability -Online -Name $_.Name }
}
Start-Service sshd; Set-Service sshd -StartupType Automatic
New-NetFirewallRule -DisplayName 'SSH-In' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -ErrorAction SilentlyContinue
# Git + Node via winget
winget install Git.Git OpenJS.NodeJS.LTS Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
if (-not (Test-Path "$App\.git")) { git clone https://github.com/Jimplas-UG/Jimplas-.git $App }
Set-Location $App
git pull 2>$null
Push-Location backend; npm install; npm run strategy:freeze 2>$null; Pop-Location
$Py = "$App\mt5_trading_system\python"
if (-not (Test-Path "$Py\.venv")) { python -m venv "$Py\.venv" }
& "$Py\.venv\Scripts\pip.exe" install -q fastapi uvicorn MetaTrader5 pydantic requests
@'
STRATEGY_FREEZE=1
PRODUCTION_MODE=1
PRODUCTION_NO_EXPIRY=1
DESK_API_PORT=8791
DESK_API_KEY=CHANGE_AFTER_LOGIN
MT5_API_URL=http://127.0.0.1:8765
MT5_SYMBOL=XAUUSD
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 Exness
FORWARD_DRY_RUN=1
FORWARD_POLL_SEC=45
RISK_PCT=0.005
MAX_DAILY_LOSS_PCT=3
MAX_DAILY_TRADES=3
MAX_API_FAILURES=8
TRADINGBOT_LOG_DIR=C:\logs\tradingbot
SAFETY_STATE_PATH=C:\logs\tradingbot\safety-state.json
'@ | Set-Content 'C:\ProgramData\Bilshenz\tradingbot.env'
# Block ALL inbound RDP (stops bots and second sessions kicking you off)
Get-NetFirewallRule -DisplayName 'RDP-Block-Public','RDP-In' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'RDP-Block-Public' -Direction Inbound -Action Block -Protocol TCP -LocalPort 3389 -ErrorAction SilentlyContinue
Write-Host 'DONE. Use SSH from your PC: ssh Administrator@104.194.140.203'
Write-Host 'Edit C:\ProgramData\Bilshenz\tradingbot.env DESK_API_KEY then install MT5 Exness on VPS.'
