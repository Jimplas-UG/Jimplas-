# Paste/run on VPS (web console or one RDP session) to wipe bot install before fresh deploy.
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Continue'
Write-Host '=== Reset VPS deployment ===' -ForegroundColor Cyan

foreach ($name in @('Bilshenz-MT5-API','Bilshenz-DeskAPI','Bilshenz-ForwardBot','Bilshenz-Watchdog')) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}

Get-Process -Name node, python -ErrorAction SilentlyContinue | Where-Object {
  $_.Path -match 'bilshenz|mt5'
} | Stop-Process -Force -ErrorAction SilentlyContinue

foreach ($p in @(
  'C:\opt\bilshenz','C:\opt\bilshenz-src','C:\opt\bilshenz-godmode.zip',
  'C:\opt\bilshenz-bundle.zip','C:\opt\Bilshenz-VPS.zip','C:\opt\vps-full-install.ps1',
  'C:\opt\vps-install.log','C:\ProgramData\Bilshenz','C:\logs\tradingbot'
)) {
  if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue; Write-Host "Removed $p" }
}

# Optional: keep RDP open; remove only our block rule
Remove-NetFirewallRule -DisplayName 'RDP-Block-Public' -ErrorAction SilentlyContinue

Write-Host 'VPS deployment cleared. Run fresh install from FRESH-START.md' -ForegroundColor Green
