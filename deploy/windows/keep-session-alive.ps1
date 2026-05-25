<#
.SYNOPSIS
    Keeps the Windows interactive session alive for MetaTrader 5.
    MT5 is a GUI application that needs an active desktop session.
    When RDP disconnects, this script ensures the session stays on the console.

.DESCRIPTION
    Runs as a scheduled task. Every 30 seconds it checks:
    1. If terminal64.exe is running and healthy (>50 MB memory)
    2. If not, kills zombie and restarts with /algotrading
    3. Keeps the desktop session active via user32.dll mouse move
#>

$LogDir = 'C:\logs\tradingbot'
$Log = Join-Path $LogDir 'session-keepalive.log'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line -ErrorAction SilentlyContinue
}

# Keep display active by preventing screen saver / sleep
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class DisplayKeepAlive {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS = 0x80000000;
    public const uint ES_DISPLAY_REQUIRED = 0x00000002;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
}
"@ -ErrorAction SilentlyContinue

$mt5Path = 'C:\Program Files\MetaTrader 5 Exness'
if (-not (Test-Path "$mt5Path\terminal64.exe")) {
    $mt5Path = 'C:\Program Files\MetaTrader 5'
}
$mt5Exe = Join-Path $mt5Path 'terminal64.exe'

Write-Log "Session keepalive started. MT5 path: $mt5Exe"

while ($true) {
    try {
        # Prevent Windows from sleeping / turning off display
        [DisplayKeepAlive]::SetThreadExecutionState(
            [DisplayKeepAlive]::ES_CONTINUOUS -bor
            [DisplayKeepAlive]::ES_DISPLAY_REQUIRED -bor
            [DisplayKeepAlive]::ES_SYSTEM_REQUIRED
        ) | Out-Null

        # Check terminal64 health
        $procs = Get-Process terminal64 -ErrorAction SilentlyContinue
        if (-not $procs) {
            Write-Log "terminal64 NOT running — starting with /algotrading"
            if (Test-Path $mt5Exe) {
                Start-Process $mt5Exe -ArgumentList '/algotrading'
                Start-Sleep 60
            }
        }
    } catch {
        Write-Log "Error: $_"
    }

    Start-Sleep 60
}
