# Full restart of Bilshenz VPS stack (Binance API + desk-api + forward bot).
$ErrorActionPreference = 'SilentlyContinue'
$ports = 8766, 8791
foreach ($port in $ports) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep 3
Start-ScheduledTask -TaskName 'Bilshenz-Binance-API' -ErrorAction SilentlyContinue
Start-Sleep 8
Start-ScheduledTask -TaskName 'Bilshenz-DeskAPI'
Start-ScheduledTask -TaskName 'Bilshenz-ForwardBot'
Start-Sleep 12
Write-Host '--- health ---'
try { Invoke-RestMethod 'http://127.0.0.1:8766/health' -TimeoutSec 10 | Format-List } catch { Write-Host "8766: $_" }
try { Invoke-RestMethod 'http://127.0.0.1:8791/health' -TimeoutSec 8 | Format-List } catch { Write-Host "8791: $_" }
try { Invoke-RestMethod 'http://127.0.0.1:8791/v1/binance/health' -TimeoutSec 12 | Format-List } catch { Write-Host "binance proxy: $_" }
