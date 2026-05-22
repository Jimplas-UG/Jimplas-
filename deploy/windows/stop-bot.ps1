$tasks = @('Bilshenz-MT5-API', 'Bilshenz-DeskAPI', 'Bilshenz-ForwardBot', 'Bilshenz-Watchdog')
foreach ($t in $tasks) {
  try { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue; Write-Host "Stopped $t" }
  catch { Write-Host "$t not running" }
}
Get-Process -Name python, node -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -match 'bilshenz|mt5_trading_system' } |
  Stop-Process -Force -ErrorAction SilentlyContinue
