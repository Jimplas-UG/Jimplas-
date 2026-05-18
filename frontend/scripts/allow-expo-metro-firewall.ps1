# Opens inbound TCP for Metro so Expo Go on Wi-Fi can download the bundle.
# Must run elevated (Administrator).
#   cd myapp
#   npm run fix:metro-firewall

$ErrorActionPreference = 'Stop'
$port = if ($env:METRO_PORT) { [int]$env:METRO_PORT } else { 8081 }

try {
  $ruleName = "Expo Metro (TCP $port)"
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain, Public |
    Out-Null
  Write-Host ""
  Write-Host "OK: Inbound TCP $port allowed on Private, Domain, and Public firewall profiles."
  Write-Host "(Public is included so Expo Go still works when Windows mis-classifies Wi-Fi as Public.)"
  Write-Host "Prefer marking your Wi‑Fi network as Private anyway: Settings → Network → Wi‑Fi → Your network → ..."
  Write-Host ""
} catch {
  Write-Host ""
  Write-Host "FAILED: Run PowerShell as Administrator, then:"
  Write-Host "  cd $PSScriptRoot\.."
  Write-Host "  npm run fix:metro-firewall"
  Write-Host ""
  exit 1
}
