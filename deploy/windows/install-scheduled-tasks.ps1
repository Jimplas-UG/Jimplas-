# Registers 24/7 scheduled tasks with restart on failure.
param([string]$AppDir = 'C:\opt\bilshenz')
$ErrorActionPreference = 'Stop'

function Register-BilshenzTask {
  param(
    [string]$Name,
    [string]$Script,
    [int]$RestartMinutes = 1
  )
  $taskName = "Bilshenz-$Name"
  $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $Script + '" -AppDir "' + $AppDir + '"'
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argLine
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes $RestartMinutes) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
  $user = "$env:USERDOMAIN\$env:USERNAME"
  $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host ('Registered: ' + $taskName)
}

$WinDeploy = $PSScriptRoot
Register-BilshenzTask -Name 'Binance-API' -Script (Join-Path $WinDeploy 'run-binance-api.ps1')
Register-BilshenzTask -Name 'MT5-API' -Script (Join-Path $WinDeploy 'run-mt5-api.ps1')
Register-BilshenzTask -Name 'DeskAPI' -Script (Join-Path $WinDeploy 'run-desk-api.ps1')
Register-BilshenzTask -Name 'ForwardBot' -Script (Join-Path $WinDeploy 'run-forward-bot.ps1')
Register-BilshenzTask -Name 'Watchdog' -Script (Join-Path $WinDeploy 'run-watchdog.ps1')
