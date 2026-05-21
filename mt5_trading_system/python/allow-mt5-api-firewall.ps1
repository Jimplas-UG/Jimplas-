# Allow inbound TCP 8765 so Expo Go on Wi-Fi can reach the MT5 Python API.
# Run elevated (Administrator):
#   cd mt5_trading_system\python
#   .\allow-mt5-api-firewall.ps1

$ErrorActionPreference = 'Stop'
$port = if ($env:PORT) { [int]$env:PORT } else { 8765 }

try {
  $ruleName = "Bilshenz MT5 API (TCP $port)"
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain, Public |
    Out-Null
  Write-Host ""
  Write-Host "OK: Inbound TCP $port allowed (MT5 Python API for phone)."
  Write-Host ""
} catch {
  Write-Host ""
  Write-Host "FAILED: Run PowerShell as Administrator, then .\allow-mt5-api-firewall.ps1"
  Write-Host ""
  exit 1
}
