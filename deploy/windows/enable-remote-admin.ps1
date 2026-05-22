# Run ONCE on VPS as Administrator (RDP) - opens SSH + WinRM for remote deploy
Set-ExecutionPolicy Bypass -Scope Process -Force

# OpenSSH Server
$cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name }
Start-Service sshd
Set-Service sshd -StartupType Automatic
New-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null

# WinRM
Enable-PSRemoting -Force -SkipNetworkProfileCheck
Set-Item WSMan:\localhost\Client\TrustedHosts -Value '*' -Force
winrm quickconfig -quiet
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/service/auth '@{Basic="true"}'
New-NetFirewallRule -DisplayName 'WinRM-HTTP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5985 -ErrorAction SilentlyContinue | Out-Null

Write-Host 'SSH (22) and WinRM (5985) enabled on Windows firewall.'
Write-Host 'Also open ports 22 and 5985 in your CLOUD provider firewall (DigitalOcean/Vultr panel).'
