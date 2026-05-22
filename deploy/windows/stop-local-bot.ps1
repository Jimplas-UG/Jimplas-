# Stop bot on THIS PC so only VPS runs trading.
Get-Job Bilshenz* -ErrorAction SilentlyContinue | Stop-Job -EA SilentlyContinue
Get-Job Bilshenz* -ErrorAction SilentlyContinue | Remove-Job -Force -EA SilentlyContinue
Get-Process -Name node, python -ErrorAction SilentlyContinue | Where-Object {
  $_.Path -match 'bilshenz|mt5_trading_system|bsv3'
} | Stop-Process -Force -ErrorAction SilentlyContinue
$p = (Get-NetTCPConnection -LocalPort 8765,8791 -State Listen -EA SilentlyContinue).OwningProcess | Select-Object -Unique
foreach ($id in $p) { Stop-Process -Id $id -Force -EA SilentlyContinue }
Write-Host 'Local bot/API stopped. Run everything on VPS only.'
