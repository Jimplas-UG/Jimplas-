# Start all trading services (scheduled tasks + optional backup window).
param([switch]$BackupOnly)
$tasks = @('Bilshenz-MT5-API', 'Bilshenz-DeskAPI', 'Bilshenz-ForwardBot', 'Bilshenz-Watchdog')
if ($BackupOnly) {
  & (Join-Path $PSScriptRoot 'start-backup-console.ps1')
  return
}
foreach ($t in $tasks) {
  try { Start-ScheduledTask -TaskName $t -ErrorAction Stop; Write-Host "Started $t" -ForegroundColor Green }
  catch { Write-Host "Failed $t : $_" -ForegroundColor Red }
}
