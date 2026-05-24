# Full restart of Bilshenz VPS stack (MT5 API + desk-api + forward bot).
$ErrorActionPreference = 'SilentlyContinue'
$ports = 8765, 8791
foreach ($port in $ports) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep 3
& (Join-Path $PSScriptRoot 'restart-mt5-api-if-hung.ps1')
Start-Sleep 8
Start-ScheduledTask -TaskName 'Bilshenz-DeskAPI'
Start-ScheduledTask -TaskName 'Bilshenz-ForwardBot'
Start-Sleep 12
Write-Host '--- health ---'
try { Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 10 | Format-List } catch { Write-Host "8765: $_" }
try { Invoke-RestMethod 'http://127.0.0.1:8791/health' -TimeoutSec 8 | Format-List } catch { Write-Host "8791: $_" }
try { Invoke-RestMethod 'http://127.0.0.1:8791/v1/mt5/health' -TimeoutSec 12 | Format-List } catch { Write-Host "proxy: $_" }
