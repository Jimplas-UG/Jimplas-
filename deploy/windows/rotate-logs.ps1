# Bilshenz Log Rotation - runs daily, keeps logs under control
$logDir = "C:\logs\tradingbot"
$archiveDir = "$logDir\archive"
$maxMB = 50

if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }

foreach ($f in Get-ChildItem "$logDir\*.log" -ErrorAction SilentlyContinue) {
    if ($f.Length -gt ($maxMB * 1MB)) {
        $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
        $dest = "$archiveDir\$($f.BaseName)-$stamp.log"
        Copy-Item $f.FullName $dest
        # Truncate original to last 1000 lines
        $tail = Get-Content $f.FullName -Tail 1000
        Set-Content $f.FullName -Value $tail
        Write-Output "Rotated $($f.Name) ($([math]::Round($f.Length/1MB,1))MB -> archive)"
    }
}

# Delete archives older than 30 days
Get-ChildItem "$archiveDir\*.log" -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force
Write-Output "Log rotation complete at $(Get-Date)"
