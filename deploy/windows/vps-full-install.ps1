# Full VPS install — run as Administrator inside RDP on 104.194.140.203
#Usage: powershell -ExecutionPolicy Bypass -File C:\opt\vps-full-install.ps1
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
$Log = 'C:\opt\vps-install.log'
function L($m) { "$(Get-Date -Format o) $m" | Tee-Object $Log -Append }

L '=== VPS full install start ==='
Set-ExecutionPolicy Bypass -Scope Process -Force
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

# Tools
foreach ($id in @('Git.Git', 'Python.Python.3.12', 'OpenJS.NodeJS.LTS')) {
  winget install --id $id -e --accept-package-agreements --accept-source-agreements 2>>$Log
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

# Repo
if (-not (Test-Path "$App\.git")) { git clone $Repo $App }
Set-Location $App
git pull 2>>$Log

# If deploy/windows missing from git, fail with clear message
if (-not (Test-Path "$App\deploy\windows\bootstrap-vps.ps1")) {
  L 'ERROR: deploy/windows not in repo. Upload deploy folder from dev machine to C:\opt\bilshenz\deploy\'
  throw 'Missing deploy/windows — copy from dev PC via RDP drive or zip.'
}

# OpenSSH for remote admin
try {
  $cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
  if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name }
  Start-Service sshd; Set-Service sshd -StartupType Automatic
  New-NetFirewallRule -DisplayName 'OpenSSH' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null
  L 'OpenSSH enabled'
} catch { L "OpenSSH skip: $_" }

# Firewall: block bot ports from internet
New-NetFirewallRule -DisplayName 'Block-8765-Internet' -Direction Inbound -Action Block -Protocol TCP -LocalPort 8765 -RemoteAddress Internet -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -DisplayName 'Allow-8765-Local' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet,127.0.0.1 -ErrorAction SilentlyContinue | Out-Null

& "$App\deploy\windows\production-setup.ps1" -AppDir $App 2>&1 | Tee-Object $Log -Append

$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (-not (Test-Path $ef)) {
  Copy-Item "$App\deploy\windows\tradingbot.env.example" $ef
}
# VPS-local MT5 only
(Get-Content $ef) -replace 'MT5_API_URL=.*', 'MT5_API_URL=http://127.0.0.1:8765' `
  -replace 'FORWARD_DRY_RUN=.*', 'FORWARD_DRY_RUN=1' `
  -replace 'change-me-long-random-secret', ([guid]::NewGuid().ToString('N')) | Set-Content $ef

& "$App\deploy\windows\install-scheduled-tasks.ps1" -AppDir $App
& "$App\deploy\windows\install-log-rotation.ps1"
& "$App\deploy\windows\start-bot.ps1"

L '=== DONE. Log in to MT5 Exness on THIS VPS, add XAUUSD, then set FORWARD_DRY_RUN=0 and restart-bot ==='
Write-Host 'Install log:' $Log -ForegroundColor Green
