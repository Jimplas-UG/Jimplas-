<#
.SYNOPSIS
    Starts the full Bilshenz stack after reboot (or logon). Run via Bilshenz-BootStack task.
#>
param([string]$AppDir = 'C:\opt\bilshenz')

$ErrorActionPreference = 'Continue'
$LogDir = 'C:\logs\tradingbot'
$Log = Join-Path $LogDir 'boot-start.log'
$Lock = Join-Path $LogDir 'boot-start.lock'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-BootLog($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $Log -Value $line -Encoding utf8 -ErrorAction SilentlyContinue
}

# Prevent overlapping runs (reboot + logon can fire twice)
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 15) {
        Write-BootLog "SKIP: boot-start ran $($age.TotalMinutes.ToString('F1')) min ago"
        exit 0
    }
}
Set-Content -Path $Lock -Value (Get-Date -Format o) -Encoding ascii

Write-BootLog "=== Boot stack start ==="
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')

$mt5Path = if ($env:MT5_TERMINAL_PATH) { $env:MT5_TERMINAL_PATH } else { 'C:\Program Files\MetaTrader 5 Exness' }
$terminalExe = Join-Path $mt5Path 'terminal64.exe'
if (-not (Test-Path $terminalExe)) {
    $terminalExe = 'C:\Program Files\MetaTrader 5\terminal64.exe'
}

# 1) MT5 terminal (needs interactive desktop)
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    if (Test-Path $terminalExe) {
        Write-BootLog "Starting terminal64 /algotrading"
        Start-Process $terminalExe -ArgumentList '/algotrading'
    } else {
        Write-BootLog "ERROR: terminal64.exe not found"
    }
} else {
    Write-BootLog "terminal64 already running"
}

Write-BootLog "Waiting 75s for MT5 terminal init..."
Start-Sleep 75

# 2) Long-running services via scheduled tasks (restart policies apply)
$tasks = @(
    @{ Name = 'Bilshenz-MT5-API'; WaitSec = 25 },
    @{ Name = 'Bilshenz-DeskAPI'; WaitSec = 15 },
    @{ Name = 'Bilshenz-ForwardBot'; WaitSec = 5 },
    @{ Name = 'Bilshenz-Watchdog'; WaitSec = 5 },
    @{ Name = 'Bilshenz-SessionKeepAlive'; WaitSec = 3 }
)

foreach ($t in $tasks) {
    try {
        $state = (Get-ScheduledTask -TaskName $t.Name -ErrorAction Stop).State
        if ($state -eq 'Running') {
            Write-BootLog "$($t.Name) already Running"
        } else {
            Write-BootLog "Starting $($t.Name)"
            Start-ScheduledTask -TaskName $t.Name -ErrorAction Stop
        }
    } catch {
        Write-BootLog "WARN $($t.Name): $($_.Exception.Message)"
    }
    Start-Sleep $t.WaitSec
}

# 3) APK download server (port 9090) for phone installs
$apkDir = Join-Path $AppDir 'frontend\dist'
if (Test-Path (Join-Path $apkDir 'bilshenz-release.apk')) {
    $on9090 = Get-NetTCPConnection -LocalPort 9090 -State Listen -ErrorAction SilentlyContinue
    if (-not $on9090) {
        Write-BootLog "Starting APK http.server on 9090"
        $py = 'python'
        if (Test-Path 'C:\opt\bilshenz\mt5_trading_system\python\.venv\Scripts\python.exe') {
            $py = 'C:\opt\bilshenz\mt5_trading_system\python\.venv\Scripts\python.exe'
        }
        Start-Process $py -ArgumentList '-m', 'http.server', '9090', '--directory', $apkDir -WindowStyle Hidden
    }
}

# 4) Health check
Start-Sleep 10
try {
    $wc = New-Object System.Net.WebClient
    $st = $wc.DownloadString('http://127.0.0.1:8765/api/status') | ConvertFrom-Json
    Write-BootLog "MT5 API: connected=$($st.connected) trade_allowed=$($st.account.trade_allowed)"
} catch {
    Write-BootLog "MT5 API: not ready yet — $($_.Exception.Message)"
}
try {
    $h = Invoke-RestMethod http://127.0.0.1:8791/health -TimeoutSec 10
    Write-BootLog "Desk API: ok=$($h.ok)"
} catch {
    Write-BootLog "Desk API: not ready — $($_.Exception.Message)"
}

Write-BootLog "=== Boot stack done ==="
