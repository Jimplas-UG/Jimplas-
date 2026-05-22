# Run ONCE inside the Windows VPS (Administrator PowerShell after RDP).
# Does not contain secrets - configure C:\ProgramData\Bilshenz\tradingbot.env after.
$ErrorActionPreference = 'Stop'
$AppDir = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'

Write-Host 'Installing OpenSSH Server (optional, needs Administrator)...' -ForegroundColor Cyan
try {
  $sshCap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
  if ($sshCap -and $sshCap.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $sshCap.Name
    Start-Service sshd -ErrorAction SilentlyContinue
    Set-Service sshd -StartupType Automatic
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
      -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue
  }
} catch {
  Write-Host 'OpenSSH skipped (run PowerShell as Administrator to enable remote SSH).' -ForegroundColor Yellow
}

if (-not (Test-Path $AppDir)) {
  git clone --depth 1 $Repo $AppDir
}
Set-Location $AppDir
git pull 2>$null

$bootstrapDir = Join-Path $AppDir 'deploy\windows'
if (-not (Test-Path (Join-Path $bootstrapDir 'production-setup.ps1'))) {
  Write-Host 'deploy/windows missing from git - ensure repo includes deploy/windows or copy from dev machine.' -ForegroundColor Yellow
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
  & (Join-Path $AppDir 'deploy\windows\production-setup.ps1') -AppDir $AppDir
} else {
  Write-Host 'Not elevated - using bootstrap-lite (jobs instead of scheduled tasks).' -ForegroundColor Yellow
  & (Join-Path $AppDir 'deploy\windows\bootstrap-lite.ps1') -AppDir $AppDir
}

Write-Host ''
Write-Host 'NEXT:' -ForegroundColor Green
Write-Host '1) Open MT5 Exness, log in, XAUUSD in Market Watch'
Write-Host '2) notepad C:\ProgramData\Bilshenz\tradingbot.env  (DESK_API_KEY, FORWARD_DRY_RUN=1)'
Write-Host '3) C:\opt\bilshenz\deploy\windows\start-bot.ps1'
Write-Host '4) C:\opt\bilshenz\deploy\windows\health-check.ps1'
