# Opens inbound TCP for Metro + desk-api + Binance bridge (Expo Go on Wi-Fi).
# Must run elevated (Administrator).
#   cd frontend
#   npm run fix:metro-firewall

$ErrorActionPreference = 'Stop'
$metroPort = if ($env:METRO_PORT) { [int]$env:METRO_PORT } else { 8081 }
$ports = @($metroPort, 8791, 8766)

try {
  foreach ($port in $ports) {
    $ruleName = "Bilshenz Expo LAN (TCP $port)"
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain, Public |
      Out-Null
  }
  Write-Host ""
  Write-Host "OK: Inbound TCP allowed on ports: $($ports -join ', ')"
  Write-Host "(Public profile included — Wi-Fi mis-classified as Public still works.)"
  Write-Host ""
} catch {
  Write-Host ""
  Write-Host "FAILED: Run PowerShell as Administrator, then:"
  Write-Host "  cd $PSScriptRoot\.."
  Write-Host "  npm run fix:metro-firewall"
  Write-Host ""
  exit 1
}
