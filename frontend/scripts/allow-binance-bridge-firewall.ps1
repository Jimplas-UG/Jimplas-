# Opens inbound TCP for Binance Python bridge (8766) so Expo Go on Wi-Fi can reach it.
# Must run elevated (Administrator).
#   cd frontend
#   npm run fix:binance-firewall

$ErrorActionPreference = 'Stop'
$port = if ($env:BINANCE_PORT) { [int]$env:BINANCE_PORT } else { 8766 }

try {
  $ruleName = "Bilshenz Binance Bridge (TCP $port)"
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain, Public |
    Out-Null
  Write-Host ""
  Write-Host "OK: Inbound TCP $port allowed (Binance bridge)."
  Write-Host "Phone URL: http://YOUR_PC_LAN_IP:$port"
  Write-Host ""
} catch {
  Write-Host ""
  Write-Host "FAILED: Run PowerShell as Administrator, then:"
  Write-Host "  cd frontend"
  Write-Host "  npm run fix:binance-firewall"
  Write-Host ""
  exit 1
}
