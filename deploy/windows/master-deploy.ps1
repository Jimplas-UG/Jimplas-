# One-shot production deployment for a fresh Windows VPS.
# Run as Administrator in an interactive RDP session (MT5 IPC requires a logged-in desktop).
#Requires -RunAsAdministrator
param(
  [string]$AppDir = 'C:\opt\bilshenz',
  [string]$Repo = '',
  [string]$Branch = 'main',
  [string]$TimeZone = 'Eastern Standard Time',
  [ValidateSet('Exness', 'IC', 'Skip')]
  [string]$InstallMt5 = 'Skip',
  [switch]$SkipPhase1
)

$ErrorActionPreference = 'Stop'
$WinDeploy = $PSScriptRoot
$RepoRoot = Split-Path (Split-Path $WinDeploy -Parent) -Parent

Write-Host @'

╔══════════════════════════════════════════════════════════╗
║  Bilshenz - Windows VPS production deploy (MT5 + bot)   ║
╚══════════════════════════════════════════════════════════╝

'@ -ForegroundColor Cyan

if (-not $SkipPhase1) {
  & (Join-Path $WinDeploy 'phase1-system-prep.ps1') -TimeZone $TimeZone
}

$setupArgs = @{ AppDir = $AppDir; Branch = $Branch; TimeZone = $TimeZone }
if ($Repo) { $setupArgs.Repo = $Repo }
elseif (Test-Path (Join-Path $AppDir '.git')) {
  Write-Host "  Using existing repo at $AppDir" -ForegroundColor DarkGray
} else {
  $setupArgs.Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
}
& (Join-Path $WinDeploy 'production-setup.ps1') @setupArgs

if ($InstallMt5 -ne 'Skip') {
  Write-Host '==> MT5 broker install (interactive wizard)' -ForegroundColor Cyan
  $mt5Script = Join-Path $AppDir 'mt5_trading_system\install-mt5-broker.ps1'
  if (-not (Test-Path $mt5Script)) {
    $mt5Script = Join-Path $RepoRoot 'mt5_trading_system\install-mt5-broker.ps1'
  }
  & $mt5Script -Broker $InstallMt5
  Write-Host 'After wizard: log in to MT5, add XAUUSD, then continue.' -ForegroundColor Yellow
  Read-Host 'Press Enter when MT5 is logged in and XAUUSD is in Market Watch'
}

$termPath = 'C:\Program Files\MetaTrader 5 Exness\terminal64.exe'
if (-not (Test-Path $termPath)) { $termPath = 'C:\Program Files\MetaTrader 5\terminal64.exe' }
& (Join-Path $WinDeploy 'install-mt5-terminal-task.ps1') -TerminalPath $termPath

Write-Host '==> Validate Python env' -ForegroundColor Cyan
& (Join-Path $WinDeploy 'validate-python-env.ps1') -AppDir $AppDir

$envFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $WinDeploy 'tradingbot.env.example') $envFile
}
Write-Host @"

=== MANUAL STEPS (required) ===
1) Edit secrets (never commit):  notepad $envFile
   - DESK_API_KEY = long random string
   - MT5_TERMINAL_PATH = folder with terminal64.exe
   - FORWARD_DRY_RUN=1  (keep until health passes)
2) Log in to MT5, add XAUUSD chart
3) Start services:
   cd $AppDir
   .\deploy\windows\start-bot.ps1
4) Validate:
   .\deploy\windows\validate-deployment.ps1

"@ -ForegroundColor Yellow

Write-Host 'MASTER_DEPLOY_SCRIPT_DONE' -ForegroundColor Green
