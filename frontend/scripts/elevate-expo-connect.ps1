# Re-launch as Administrator (UAC prompt), then open firewall + start Metro.
param([switch]$NoMetro)

$root = Split-Path $PSScriptRoot -Parent
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
  Write-Host "Requesting Administrator approval (UAC) to open firewall port 8081..." -ForegroundColor Yellow
  $argList = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
  if ($NoMetro) { $argList += ' -NoMetro' }
  Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
  exit 0
}

Set-Location $root
$port = if ($env:METRO_PORT) { $env:METRO_PORT } else { '8081' }

Write-Host ""
Write-Host "=== Bilshenz Expo Go (Administrator) ===" -ForegroundColor Cyan

$ruleName = "Expo Metro TCP $port"
netsh advfirewall firewall delete rule name="$ruleName" 2>$null | Out-Null
netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port profile=any | Out-Null
foreach ($extraPort in @('8766', '8791')) {
  $extraRule = "Bilshenz Desk TCP $extraPort"
  netsh advfirewall firewall delete rule name="$extraRule" 2>$null | Out-Null
  netsh advfirewall firewall add rule name="$extraRule" dir=in action=allow protocol=TCP localport=$extraPort profile=any | Out-Null
}
Write-Host "OK: Firewall allows inbound TCP $port, 8766, 8791" -ForegroundColor Green

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*' -and $_.PrefixOrigin -eq 'Dhcp' } |
  Select-Object -First 1).IPAddress
if (-not $ip) { $ip = '192.168.1.154' }

Write-Host ""
Write-Host "In Expo Go 52, enter this URL:" -ForegroundColor White
Write-Host "  exp://${ip}:${port}" -ForegroundColor Yellow
Write-Host ""
Write-Host "Phone must be on the SAME Wi-Fi. Turn OFF mobile data." -ForegroundColor DarkGray
Write-Host ""

$env:CI = 'false'
$env:EXPO_PACKAGER_PINNED = $ip
Remove-Item Env:EXPO_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:EXPO_FORCE_TUNNEL -ErrorAction SilentlyContinue
Remove-Item Env:REACT_NATIVE_PACKAGER_HOSTNAME -ErrorAction SilentlyContinue
Remove-Item Env:EXPO_PACKAGER_HOSTNAME -ErrorAction SilentlyContinue

$env:EXPO_LAN_IP = $ip
node scripts/make-expo-qr.js
Start-Process (Join-Path $root 'expo-go-qr.html')

if ($NoMetro) { exit 0 }

Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep 2

Write-Host "Starting Metro..." -ForegroundColor Green
node scripts/run-expo-go.js --lan --clear
