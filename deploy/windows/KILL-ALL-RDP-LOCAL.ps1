# Run on YOUR PC before any VPS work
Get-Process mstsc -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process | Where-Object { $_.ProcessName -eq 'mstsc' } | Stop-Process -Force
cmdkey /delete:TERMSRV/104.194.140.203 2>$null
cmdkey /delete:TERMSRV/104.194.140.203* 2>$null
Write-Host 'All local RDP to VPS killed. Close browser VPS console tab too.'
Write-Host 'Wait 2 minutes before SSH or console only.'
