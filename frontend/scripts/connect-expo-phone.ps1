# One-shot: firewall + fresh Metro (LAN) + QR page.
# Run as Administrator for firewall step (right-click PowerShell → Run as administrator).
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$port = if ($env:METRO_PORT) { $env:METRO_PORT } else { '8081' }

Write-Host ""
Write-Host "=== Bilshenz Expo Go connect ===" -ForegroundColor Cyan

# Firewall (needs admin)
$ruleName = "Expo Metro TCP $port"
try {
  netsh advfirewall firewall delete rule name="$ruleName" 2>$null | Out-Null
  netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port profile=any | Out-Null
  Write-Host "OK: Firewall allows inbound TCP $port" -ForegroundColor Green
} catch {
  Write-Host "WARN: Could not add firewall rule (run this script as Administrator)" -ForegroundColor Yellow
  Write-Host "      Or use USB: npm run setup:adb && npm run start:usb" -ForegroundColor Yellow
}

# Free port
Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep 2

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*' -and $_.PrefixOrigin -eq 'Dhcp' } |
  Select-Object -First 1).IPAddress
if (-not $ip) { $ip = '127.0.0.1' }

Write-Host "LAN IP: $ip" -ForegroundColor DarkGray
Write-Host "URL:    exp://${ip}:${port}" -ForegroundColor White
Write-Host ""

$env:CI = 'false'
Remove-Item Env:EXPO_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:REACT_NATIVE_PACKAGER_HOSTNAME -ErrorAction SilentlyContinue
Remove-Item Env:EXPO_PACKAGER_HOSTNAME -ErrorAction SilentlyContinue
$env:EXPO_PACKAGER_PINNED = $ip

node scripts/make-expo-qr.js
$html = Join-Path $root 'expo-go-qr.html'
if (Test-Path $html) { Start-Process $html }

Write-Host "Starting Metro (--lan --clear)..." -ForegroundColor Green
node scripts/run-expo-go.js --lan --clear
