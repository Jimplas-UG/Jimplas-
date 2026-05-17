# Opens inbound TCP for Metro so Expo Go on Wi-Fi can download the bundle.
# Must run elevated (Administrator).
#   cd myapp
#   npm run fix:metro-firewall

$ErrorActionPreference = 'Stop'
$port = if ($env:METRO_PORT) { [int]$env:METRO_PORT } else { 8081 }

try {
  $ruleName = "Expo Metro (TCP $port)"
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain |
    Out-Null
  Write-Host ""
  Write-Host "OK: Inbound TCP $port allowed on Private and Domain profiles."
  Write-Host "Also set your Wi-Fi network to Private (Settings -> Network -> Wi-Fi -> properties)."
  Write-Host ""
} catch {
  Write-Host ""
  Write-Host "FAILED: Run PowerShell as Administrator, then:"
  Write-Host "  cd $PSScriptRoot\.."
  Write-Host "  npm run fix:metro-firewall"
  Write-Host ""
  exit 1
}
