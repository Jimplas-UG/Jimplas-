# Run ON THE VPS in Administrator PowerShell (RDP or web console).
# Fixes OpenSSH Server so SSH from your PC stops failing instantly.
#Requires -RunAsAdministrator
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'

Write-Host '=== OpenSSH Server repair ===' -ForegroundColor Cyan

# Install server capability
$cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') {
  Write-Host 'Installing OpenSSH Server...'
  Add-WindowsCapability -Online -Name $cap.Name
}

# Ensure sshd config exists
$cfgDir = "$env:ProgramData\ssh"
$cfg = Join-Path $cfgDir 'sshd_config'
if (-not (Test-Path $cfg)) {
  if (Test-Path "$env:ProgramData\ssh\sshd_config_default") {
    Copy-Item "$env:ProgramData\ssh\sshd_config_default" $cfg
  }
}

# Allow password auth (default Windows VPS)
$content = Get-Content $cfg -Raw -ErrorAction SilentlyContinue
if ($content -and $content -notmatch 'PasswordAuthentication\s+yes') {
  Add-Content $cfg "`nPasswordAuthentication yes"
}
if ($content -and $content -match '#PubkeyAuthentication') {
  (Get-Content $cfg) -replace '#PubkeyAuthentication yes', 'PubkeyAuthentication yes' | Set-Content $cfg
}

# Firewall
if (-not (Get-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -EA SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH-Server-In-TCP' `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}

# Service
Set-Service sshd -StartupType Automatic
Start-Service sshd
Restart-Service sshd -Force

Write-Host ''
Write-Host '--- Status ---' -ForegroundColor Cyan
Get-Service sshd | Format-Table Name, Status, StartType
Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, State

Write-Host ''
Write-Host 'FIX_SSH_OK - also open TCP 22 in your CLOUD provider firewall.' -ForegroundColor Green
Write-Host 'From your PC test: ssh -v Administrator@YOUR_VPS_IP' -ForegroundColor Yellow
