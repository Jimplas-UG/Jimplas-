# Install broker-branded MetaTrader 5 (Exness and/or IC Markets SC).
# The generic "MetaTrader 5" from metaquotes.net often fails Python IPC / has no broker symbols.
#
# Usage (run PowerShell as Administrator):
#   cd mt5_trading_system
#   .\install-mt5-broker.ps1 -Broker Exness
#   .\install-mt5-broker.ps1 -Broker IC
#   .\install-mt5-broker.ps1 -Broker Both
#
# After install: log in inside MT5 (File → Login to trade account), then:
#   set MT5_TERMINAL_PATH to the folder shown at the end
#   npm run mt5-api   (from backend or myapp)

param(
  [ValidateSet('Exness', 'IC', 'Both')]
  [string]$Broker = 'Exness',
  [switch]$SkipRemoveGeneric
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$dl = Join-Path $here 'installers'
New-Item -ItemType Directory -Force -Path $dl | Out-Null

$installers = @{
  Exness = @{
    Url  = 'https://download.metatrader.com/cdn/web/exness.technologies.ltd/mt5/exness5setup.exe'
    File = Join-Path $dl 'exness5setup.exe'
    Name = 'Exness MetaTrader 5'
    # Typical path after install (verify in MT5: File → Open Data Folder → parent of MQL5)
    DefaultPath = 'C:\Program Files\MetaTrader 5 Exness\terminal64.exe'
  }
  IC = @{
    Url  = 'https://download.metatrader.com/cdn/web/icmarkets.sc/mt5/icmarketssc5setup.exe'
    File = Join-Path $dl 'icmarketssc5setup.exe'
    Name = 'IC Markets (SC) MetaTrader 5'
    DefaultPath = 'C:\Program Files\MetaTrader 5 IC Markets (SC)\terminal64.exe'
  }
}

function Stop-Mt5Processes {
  Get-Process terminal64, metaeditor64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path -match 'mt5_trading_system'
  } | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

function Remove-GenericMt5 {
  $paths = @(
    'C:\Program Files\MetaTrader 5',
    "${env:ProgramFiles(x86)}\MetaTrader 5"
  )
  foreach ($p in $paths) {
    if (Test-Path $p) {
      Write-Host "Removing generic MT5: $p" -ForegroundColor Yellow
      Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
    }
  }
  # Uninstall entry if present (MetaQuotes generic)
  $uninstallKeys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
  )
  foreach ($key in $uninstallKeys) {
    Get-ItemProperty $key -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -eq 'MetaTrader 5' -and $_.Publisher -match 'MetaQuotes' } |
      ForEach-Object {
        if ($_.UninstallString) {
          Write-Host "Running uninstaller: $($_.DisplayName)" -ForegroundColor Yellow
          $cmd = $_.UninstallString -replace '/I', '/X' -replace 'MsiExec.exe', 'MsiExec.exe /qn'
          if ($cmd -match 'MsiExec') { Start-Process 'msiexec.exe' -ArgumentList '/X', $_.PSChildName, '/qn' -Wait -ErrorAction SilentlyContinue }
        }
      }
  }
}

function Get-Installer([string]$key) {
  $i = $installers[$key]
  if (-not (Test-Path $i.File)) {
    Write-Host "Downloading $($i.Name) ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $i.Url -OutFile $i.File -UseBasicParsing
  } else {
    Write-Host "Using cached $($i.File)" -ForegroundColor DarkGray
  }
  return $i
}

function Start-BrokerInstaller([hashtable]$i) {
  Write-Host ""
  Write-Host "Launching installer: $($i.Name)" -ForegroundColor Green
  Write-Host "  Complete the wizard, then log in (File → Login to trade account)." -ForegroundColor DarkGray
  Write-Host "  Expected terminal: $($i.DefaultPath)" -ForegroundColor DarkGray
  $proc = Start-Process -FilePath $i.File -Wait -PassThru
  if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne $null) {
    Write-Host "Installer exit code: $($proc.ExitCode)" -ForegroundColor Yellow
  }
}

# --- main ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin -and -not $SkipRemoveGeneric) {
  Write-Host "Not running as Administrator — skipping removal of generic MT5." -ForegroundColor Yellow
  Write-Host "After broker install: uninstall 'MetaTrader 5' in Windows Settings, or delete:" -ForegroundColor Yellow
  Write-Host "  C:\Program Files\MetaTrader 5" -ForegroundColor DarkGray
  Write-Host "Re-run with -SkipRemoveGeneric if you already removed it." -ForegroundColor DarkGray
  $SkipRemoveGeneric = $true
}

Stop-Mt5Processes
if (-not $SkipRemoveGeneric) {
  Remove-GenericMt5
}

$toInstall = switch ($Broker) {
  'Both' { @('Exness', 'IC') }
  'IC'   { @('IC') }
  default { @('Exness') }
}

foreach ($key in $toInstall) {
  $i = Get-Installer $key
  Start-BrokerInstaller $i
}

Write-Host ""
Write-Host '=== Done ===' -ForegroundColor Green
Write-Host 'Set terminal path before starting the Python API (PowerShell):'
foreach ($key in $toInstall) {
  $p = $installers[$key].DefaultPath
  $dir = Split-Path $p -Parent
  if (Test-Path $p) {
    Write-Host "  [OK] $key → `$env:MT5_TERMINAL_PATH='$dir'" -ForegroundColor Cyan
  } else {
    Write-Host "  [?] $key → check install folder; set MT5_TERMINAL_PATH to folder containing terminal64.exe" -ForegroundColor Yellow
    Write-Host "      (looked for $p)" -ForegroundColor DarkGray
  }
}
Write-Host ''
Write-Host 'Exness demo: server Exness-MT5Trial9 · IC demo: server ICMarketsSC-Demo'
Write-Host 'Then: cd backend && npm run mt5-api'
Write-Host 'Backtest: npm run backtest:xau12mo:realistic'
