# Backup runtime — detached PowerShell windows if scheduled tasks fail.
param([string]$AppDir = 'C:\opt\bilshenz')
$WinDeploy = $PSScriptRoot
$names = @{
  'BilshenzBackup-MT5'     = 'run-mt5-api.ps1'
  'BilshenzBackup-Desk'    = 'run-desk-api.ps1'
  'BilshenzBackup-Forward' = 'run-forward-bot.ps1'
  'BilshenzBackup-Watch'   = 'run-watchdog.ps1'
}
foreach ($entry in $names.GetEnumerator()) {
  $script = Join-Path $WinDeploy $entry.Value
  Start-Process powershell -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass',
    '-File', $script, '-AppDir', $AppDir
  ) -WindowStyle Minimized
  Write-Host "Backup window: $($entry.Key)"
}
