<#
.SYNOPSIS
    Configure Bilshenz to auto-start on every reboot (logon + delayed boot backup).
    Run as Administrator: powershell -ExecutionPolicy Bypass -File install-boot-autostart.ps1
#>
param([string]$AppDir = 'C:\opt\bilshenz')

$ErrorActionPreference = 'Stop'
$WinDeploy = $PSScriptRoot
$bootScript = Join-Path $WinDeploy 'boot-start-bilshenz.ps1'
$user = 'Administrator'

Write-Host "==> Bilshenz boot autostart" -ForegroundColor Cyan

# Ensure auto-login (required for MT5 GUI + Interactive tasks)
$wl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
Set-ItemProperty -Path $wl -Name 'AutoAdminLogon' -Value '1' -Type String
Set-ItemProperty -Path $wl -Name 'DefaultUserName' -Value $user -Type String
if (-not (Get-ItemProperty -Path $wl -Name 'DefaultDomainName' -ErrorAction SilentlyContinue)) {
    Set-ItemProperty -Path $wl -Name 'DefaultDomainName' -Value '.' -Type String
}
Write-Host "Auto-login: Administrator (password must already be set in registry)" -ForegroundColor Gray

# Remove BootTrigger from individual services — one orchestrator starts them in order
$serviceTasks = @(
    'Bilshenz-MT5-Terminal',
    'Bilshenz-MT5-API',
    'Bilshenz-DeskAPI',
    'Bilshenz-ForwardBot',
    'Bilshenz-Watchdog',
    'Bilshenz-SessionKeepAlive'
)

foreach ($taskName in $serviceTasks) {
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $changed = $false
        foreach ($tr in $task.Triggers) {
            if ($tr.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger') {
                $tr.Enabled = $false
                $changed = $true
            }
        }
        if ($changed) {
            Set-ScheduledTask -TaskName $taskName -Trigger $task.Triggers | Out-Null
            Write-Host "  $taskName : boot trigger disabled" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "  $taskName : skip ($($_.Exception.Message))" -ForegroundColor Yellow
    }
}

# Register orchestrator: LOGON (primary) + BOOT delay 3 min (backup)
$argLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$bootScript`" -AppDir `"$AppDir`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argLine

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$triggerBoot.Delay = 'PT3M'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest

Unregister-ScheduledTask -TaskName 'Bilshenz-BootStack' -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'Bilshenz-BootStack' `
    -Action $action -Trigger @($triggerLogon, $triggerBoot) `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered: Bilshenz-BootStack (AtLogOn + AtStartup +3min)" -ForegroundColor Green

# Open firewall for app + APK if missing
foreach ($pair in @(
        @{ Name = 'Bilshenz-DeskAPI-8791'; Port = 8791 },
        @{ Name = 'Bilshenz-APK-9090'; Port = 9090 }
    )) {
    if (-not (Get-NetFirewallRule -DisplayName $pair.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $pair.Name -Direction Inbound -Protocol TCP `
            -LocalPort $pair.Port -Action Allow -Profile Any | Out-Null
        Write-Host "Firewall: opened port $($pair.Port)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Done. After next reboot the stack starts automatically within ~3 minutes." -ForegroundColor Green
Write-Host "Log: C:\logs\tradingbot\boot-start.log" -ForegroundColor Gray
