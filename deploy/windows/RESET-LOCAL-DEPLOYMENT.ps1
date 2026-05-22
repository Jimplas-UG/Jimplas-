# Wipes local trading-bot deployment. Safe to re-run. Does not touch repo source (bsv3).
# Usage: powershell -ExecutionPolicy Bypass -File RESET-LOCAL-DEPLOYMENT.ps1
param([switch]$Force)
$ErrorActionPreference = 'Continue'

Write-Host '=== Reset local deployment ===' -ForegroundColor Cyan

# Stop jobs / processes / ports
Get-Job Bilshenz*,*LOCK-NO-RDP* -ErrorAction SilentlyContinue | Stop-Job -EA SilentlyContinue
Get-Job Bilshenz*,*LOCK-NO-RDP* -ErrorAction SilentlyContinue | Remove-Job -Force -EA SilentlyContinue
Get-Process mstsc -ErrorAction SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
cmdkey /delete:TERMSRV/104.194.140.203 2>$null | Out-Null

foreach ($name in @('Bilshenz-MT5-API','Bilshenz-DeskAPI','Bilshenz-ForwardBot','Bilshenz-Watchdog')) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Task removed (if existed): $name"
}

Get-Process -Name node, python -ErrorAction SilentlyContinue | Where-Object {
  $_.Path -match 'bilshenz|mt5_trading_system|bsv3'
} | Stop-Process -Force -ErrorAction SilentlyContinue
foreach ($port in 8765, 8791) {
  (Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue).OwningProcess |
    Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }
}

$paths = @(
  'C:\opt\bilshenz',
  'C:\opt\bilshenz-src',
  'C:\opt\bilshenz-godmode.zip',
  'C:\opt\bilshenz-bundle.zip',
  'C:\opt\vps-full-install.ps1',
  'C:\opt\vps-install.log',
  'C:\opt\bootstrap.log',
  'C:\ProgramData\Bilshenz',
  'C:\logs\tradingbot'
)
foreach ($p in $paths) {
  if (Test-Path $p) {
    if (-not $Force) { Write-Host "Remove: $p" -ForegroundColor Yellow }
    Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($f in @('Bilshenz-VPS.zip','EXPERT-VPS-RUN.ps1','VPS-104.194.140.203.rdp')) {
  $p = Join-Path $desktop $f
  if (Test-Path $p) { Remove-Item $p -Force; Write-Host "Removed $p" }
}

foreach ($pat in @('bilshenz*.zip','bilshenz-godmode.zip','bilshenz-vps-bundle.zip')) {
  Get-ChildItem $env:TEMP -Filter $pat -ErrorAction SilentlyContinue | Remove-Item -Force
}

$bundle = Join-Path $PSScriptRoot 'bilshenz-vps-bundle.zip'
if (Test-Path $bundle) { Remove-Item $bundle -Force; Write-Host "Removed repo bundle $bundle" }

Write-Host ''
Write-Host 'Local deployment cleared.' -ForegroundColor Green
Write-Host 'Repo code at bsv3 is unchanged. Next: deploy\windows\FRESH-START.md' -ForegroundColor Cyan
