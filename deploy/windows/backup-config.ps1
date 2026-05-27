param([string]$BackupRoot = 'C:\Backups\Bilshenz')

$stamp = (Get-Date).ToString('yyyy-MM-dd_HHmmss')
$dest = Join-Path $BackupRoot $stamp
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Critical config files
$configFiles = @(
    'C:\ProgramData\Bilshenz\tradingbot.env',
    'C:\logs\tradingbot\safety-state.json',
    'C:\logs\tradingbot\safety.jsonl',
    'C:\logs\tradingbot\reconnect.jsonl'
)
foreach ($f in $configFiles) {
    if (Test-Path $f) { Copy-Item $f $dest -Force }
}

# Scheduled task XML exports
$taskDir = Join-Path $dest 'tasks'
New-Item -ItemType Directory -Force -Path $taskDir | Out-Null
foreach ($t in @('Bilshenz-ForwardBot','Bilshenz-DeskAPI','Bilshenz-Watchdog','Bilshenz-SessionKeepAlive','Bilshenz-MT5-Terminal','Bilshenz-LogRotation')) {
    try { schtasks /Query /TN $t /XML > "$taskDir\$t.xml" 2>$null } catch {}
}

# Recent logs (last 5000 lines each)
$logDir = Join-Path $dest 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
foreach ($log in Get-ChildItem 'C:\logs\tradingbot\*.log' -ErrorAction SilentlyContinue) {
    Get-Content $log.FullName -Tail 5000 -ErrorAction SilentlyContinue |
        Set-Content (Join-Path $logDir $log.Name) -Encoding utf8
}

# MT5 account snapshot
try {
    $wc = New-Object System.Net.WebClient
    $status = $wc.DownloadString('http://127.0.0.1:8765/api/status')
    Set-Content (Join-Path $dest 'mt5-status-snapshot.json') $status -Encoding utf8
    $deals = $wc.DownloadString('http://127.0.0.1:8765/api/logs?limit=200')
    Set-Content (Join-Path $dest 'mt5-deals-snapshot.json') $deals -Encoding utf8
} catch {}

# Prune backups older than 30 days
Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Recurse -Force

$count = (Get-ChildItem $dest -Recurse -File).Count
Write-Output "Backup complete: $dest ($count files)"
