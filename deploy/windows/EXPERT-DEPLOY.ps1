# Expert deploy from YOUR PC - one RDP session, no Cursor mstsc, no SSH required.
# Usage: powershell -ExecutionPolicy Bypass -File EXPERT-DEPLOY.ps1
$ErrorActionPreference = 'Stop'
$Vps = if ($env:VPS_HOST) { $env:VPS_HOST } else { '104.194.140.203' }
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Desktop = [Environment]::GetFolderPath('Desktop')
$Zip = Join-Path $Desktop 'Bilshenz-VPS.zip'
$Rdp = Join-Path $Desktop "VPS-$Vps.rdp"

& (Join-Path $PSScriptRoot 'KILL-ALL-RDP-LOCAL.ps1')

Write-Host 'Building VPS bundle (deploy + backend + MT5 API)...' -ForegroundColor Cyan
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path @(
  (Join-Path $RepoRoot 'deploy\windows'),
  (Join-Path $RepoRoot 'backend'),
  (Join-Path $RepoRoot 'mt5_trading_system\python')
) -DestinationPath $Zip -Force
Copy-Item (Join-Path $PSScriptRoot 'EXPERT-VPS-RUN.ps1') (Join-Path $Desktop 'EXPERT-VPS-RUN.ps1') -Force

@"
screen mode id:i:2
use multimon:i:0
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
winposstr:s:0,1,0,0,1920,1080
compression:i:1
keyboardhook:i:2
audiocapturemode:i:0
videoplaybackmode:i:1
connection type:i:7
networkautodetect:i:1
bandwidthautodetect:i:1
displayconnectionbar:i:1
enableworkspacereconnect:i:0
disable wallpaper:i:0
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
full address:s:$Vps
audiomode:i:0
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
redirectclipboard:i:1
redirectposdevices:i:0
drivestoredirect:s:*
autoreconnection enabled:i:0
authentication level:i:2
prompt for credentials:i:1
negotiate security layer:i:1
remoteapplicationmode:i:0
alternate shell:s:
shell working directory:s:
gatewayhostname:s:
gatewayusagemethod:i:4
gatewaycredentialssource:i:4
gatewayprofileusagemethod:i:0
promptcredentialonce:i:1
"@ | Set-Content $Rdp -Encoding ASCII

Write-Host ''
Write-Host '=== EXPERT STEPS (you do this once) ===' -ForegroundColor Green
Write-Host "1. Double-click Desktop\VPS-$Vps.rdp  (ONE window only)"
Write-Host '2. Log in as Administrator (panel password)'
Write-Host '3. On VPS: open PowerShell as Administrator, run:'
Write-Host "   powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Desktop\EXPERT-VPS-RUN.ps1"
Write-Host '   If Desktop file missing, run from shared drive:'
Write-Host '   powershell -ExecutionPolicy Bypass -File \\tsclient\C\Users\Amoskole\Desktop\EXPERT-VPS-RUN.ps1'
Write-Host ''
Write-Host "Bundle: $Zip" -ForegroundColor Yellow
Write-Host "Runner: $(Join-Path $Desktop 'EXPERT-VPS-RUN.ps1')" -ForegroundColor Yellow
Write-Host 'Do NOT run LOCK-NO-RDP while using RDP.' -ForegroundColor DarkYellow
