# Opens inbound TCP for Metro + desk-api + Binance bridge (Expo Go on Wi-Fi).
# Must run elevated (Administrator).
#   cd frontend
#   npm run fix:metro-firewall

$ErrorActionPreference = 'Stop'
$metroPort = if ($env:METRO_PORT) { [int]$env:METRO_PORT } else { 8081 }
$ports = @($metroPort, 8791, 8766)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
  Write-Host ""
  Write-Host "Requesting Administrator approval (UAC) to open firewall..." -ForegroundColor Yellow
  Start-Process powershell.exe -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
  exit 0
}

foreach ($port in $ports) {
  foreach ($ruleName in @("Bilshenz Expo LAN TCP $port", "Expo Metro TCP $port", "Bilshenz Desk TCP $port")) {
    netsh advfirewall firewall delete rule name="$ruleName" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port profile=any | Out-Null
  }
}

Write-Host ""
Write-Host "OK: Inbound TCP allowed on ports: $($ports -join ', ')"
Write-Host "(Public profile included - Wi-Fi marked Public still works.)"
Write-Host ""
