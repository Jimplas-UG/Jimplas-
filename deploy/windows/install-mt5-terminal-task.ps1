# Phase 5 — MT5 terminal: auto-start at logon + restart if crashed.
#Requires -RunAsAdministrator
param(
  [string]$TerminalPath = 'C:\Program Files\MetaTrader 5 Exness\terminal64.exe',
  [int]$CheckIntervalMinutes = 5
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $TerminalPath)) {
  $alt = 'C:\Program Files\MetaTrader 5\terminal64.exe'
  if (Test-Path $alt) { $TerminalPath = $alt } else {
    throw "MT5 not found. Install broker MT5 first, then re-run with -TerminalPath"
  }
}

$watchScript = Join-Path $PSScriptRoot 'watch-mt5-terminal.ps1'
@'
param(
  [string]$TerminalExe,
  [int]$GraceSec = 30
)
$ErrorActionPreference = 'SilentlyContinue'
$logDir = 'C:\logs\tradingbot'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'mt5-terminal-watch.log'

function Write-Log([string]$msg) {
  $line = "$(Get-Date -Format 'o') $msg"
  Add-Content -Path $log -Value $line
  Write-Host $line
}

if (-not (Test-Path $TerminalExe)) {
  Write-Log "ERROR missing terminal: $TerminalExe"
  exit 1
}

$running = Get-Process terminal64 -ErrorAction SilentlyContinue
if (-not $running) {
  Write-Log "RESTART starting MT5: $TerminalExe"
  $row = @{ ts = (Get-Date -Format 'o'); event = 'restart'; message = 'mt5_terminal_start' } | ConvertTo-Json -Compress
  Add-Content (Join-Path $logDir 'reconnect.jsonl') -Value $row
  Start-Process -FilePath $TerminalExe
  Start-Sleep -Seconds $GraceSec
} else {
  Write-Log "OK terminal64 pid=$($running.Id -join ',')"
}
'@ | Set-Content -Path $watchScript -Encoding UTF8

# At logon: ensure MT5 is running
$taskStart = 'Bilshenz-MT5-Terminal'
$actionStart = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument @(
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchScript,
  '-TerminalExe', $TerminalPath
)
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskStart -Action $actionStart -Trigger $triggerLogon `
  -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered: $taskStart (At logon)"

# Every N minutes: restart if crashed
$taskWatch = 'Bilshenz-MT5-Terminal-Watch'
$triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes $CheckIntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $taskWatch -Action $actionStart -Trigger $triggerRepeat `
  -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered: $taskWatch (every ${CheckIntervalMinutes}m)"

Write-Host 'MT5_TERMINAL_TASKS_OK' -ForegroundColor Green
