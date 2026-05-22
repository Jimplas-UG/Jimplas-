# Full Windows VPS production setup. Run as Administrator.
#Requires -RunAsAdministrator
param(
  [string]$AppDir = 'C:\opt\bilshenz',
  [string]$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git',
  [string]$Branch = 'main',
  [string]$TimeZone = 'Eastern Standard Time'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LogDir = 'C:\logs\tradingbot'
$EnvDir = 'C:\ProgramData\Bilshenz'
$EnvFile = Join-Path $EnvDir 'tradingbot.env'

Write-Host '==> Phase 1 system prep' -ForegroundColor Cyan
$phase1 = Join-Path $PSScriptRoot 'phase1-system-prep.ps1'
if (Test-Path $phase1) {
  & $phase1 -TimeZone $TimeZone
} else {
  Write-Host '==> Timezone (phase1 script missing — fallback)' -ForegroundColor Yellow
  try { Set-TimeZone -Id $TimeZone } catch { tzutil /s $TimeZone }
}

Write-Host '==> Directories' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $AppDir, $LogDir, $EnvDir | Out-Null

Write-Host '==> Install tools (winget)' -ForegroundColor Cyan
$pkgs = @('Git.Git', 'Python.Python.3.12', 'OpenJS.NodeJS.LTS')
foreach ($p in $pkgs) {
  winget install --id $p -e --accept-package-agreements --accept-source-agreements 2>$null
}
# Refresh PATH for current session
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
  [System.Environment]::GetEnvironmentVariable('Path', 'User')

Write-Host '==> Clone or update repo' -ForegroundColor Cyan
$appReady = Test-Path (Join-Path $AppDir 'backend\package.json')
if ($appReady) {
  Write-Host "  Code present at $AppDir" -ForegroundColor DarkGray
} elseif ((Resolve-Path $RepoRoot -EA SilentlyContinue).Path -ne (Resolve-Path $AppDir -EA SilentlyContinue).Path -and
  (Test-Path (Join-Path $RepoRoot 'backend\package.json'))) {
  Write-Host "  Copying local repo from $RepoRoot -> $AppDir" -ForegroundColor DarkGray
  New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
  robocopy $RepoRoot $AppDir /E /XD node_modules .git .venv __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np 2>&1 | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
} elseif (-not (Test-Path (Join-Path $AppDir '.git'))) {
  git clone --depth 1 -b $Branch $Repo $AppDir
} else {
  Push-Location $AppDir
  git fetch origin
  git checkout $Branch
  git pull --ff-only
  Pop-Location
}

Write-Host '==> Node backend' -ForegroundColor Cyan
Push-Location (Join-Path $AppDir 'backend')
npm ci 2>$null; if ($LASTEXITCODE -ne 0) { npm install }
npm run strategy:freeze 2>$null
Pop-Location

Write-Host '==> Python venv (MT5 API)' -ForegroundColor Cyan
$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$Venv = Join-Path $PyDir '.venv'
if (-not (Test-Path $Venv)) {
  python -m venv $Venv
}
& (Join-Path $Venv 'Scripts\pip.exe') install --upgrade pip wheel
$Req = Join-Path $PSScriptRoot 'requirements.txt'
& (Join-Path $Venv 'Scripts\pip.exe') install -r $Req

Write-Host '==> Env file' -ForegroundColor Cyan
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $PSScriptRoot 'tradingbot.env.example') $EnvFile
  Write-Host "Created $EnvFile — edit secrets before live trading." -ForegroundColor Yellow
}

Write-Host '==> Firewall (RDP + block bot ports from internet)' -ForegroundColor Cyan
if (-not (Get-NetFirewallRule -DisplayName 'Bilshenz-Block-8765-Public' -EA SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'Bilshenz-Block-8765-Public' -Direction Inbound -Action Block `
    -Protocol TCP -LocalPort 8765 -RemoteAddress Internet 2>$null
}
if (-not (Get-NetFirewallRule -DisplayName 'Bilshenz-Allow-8765-Local' -EA SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'Bilshenz-Allow-8765-Local' -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet,127.0.0.1 2>$null
}

Write-Host '==> Scheduled tasks (24/7)' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'install-scheduled-tasks.ps1') -AppDir $AppDir

Write-Host '==> Log rotation task' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'install-log-rotation.ps1')

Write-Host ''
Write-Host 'SETUP_OK' -ForegroundColor Green
Write-Host "1) Open MT5 Exness, log in, add XAUUSD"
Write-Host "2) Edit: notepad $EnvFile"
Write-Host "3) Start services: .\deploy\windows\start-bot.ps1"
Write-Host "4) Health: .\deploy\windows\health-check.ps1"
Write-Host 'Keep an RDP session logged in — MT5 IPC requires an interactive desktop.' -ForegroundColor Yellow
