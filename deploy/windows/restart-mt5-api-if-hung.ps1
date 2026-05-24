# Restart MT5 Python API if /health does not respond (fixes CLOSE_WAIT hangs).
$ErrorActionPreference = 'SilentlyContinue'
$url = 'http://127.0.0.1:8765/health'
$ok = $false
try {
  $r = Invoke-RestMethod $url -TimeoutSec 6
  $ok = [bool]$r.ok
} catch {}
if ($ok) { exit 0 }
$conns = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
  Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
}
Start-Sleep 2
Start-ScheduledTask -TaskName 'Bilshenz-MT5-API'
Write-Host 'MT5_API_RESTARTED'
