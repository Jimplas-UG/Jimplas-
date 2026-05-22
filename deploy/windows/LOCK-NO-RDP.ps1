# Run on YOUR PC — blocks all Remote Desktop to VPS for 30 minutes while you use web console only.
# Do NOT open mstsc yourself during this window.
param([int]$Minutes = 30)
$Vps = '104.194.140.203'
cmdkey /delete:TERMSRV/$Vps 2>$null | Out-Null
Write-Host "Blocking mstsc -> $Vps for $Minutes minutes. Use HOSTING WEB CONSOLE only." -ForegroundColor Cyan
Write-Host "Paste: CONSOLE-PASTE-INSTALL.ps1 in provider console." -ForegroundColor Yellow
$end = (Get-Date).AddMinutes($Minutes)
while ((Get-Date) -lt $end) {
  Get-Process mstsc -ErrorAction SilentlyContinue | ForEach-Object {
    $conn = Get-NetTCPConnection -OwningProcess $_.Id -ErrorAction SilentlyContinue |
      Where-Object { $_.RemoteAddress -eq $Vps -and $_.RemotePort -eq 3389 }
    if ($conn) {
      Stop-Process -Id $_.Id -Force
      Write-Host "$(Get-Date -Format HH:mm:ss) Stopped mstsc that was connecting to VPS"
    }
  }
  Start-Sleep -Seconds 5
}
Write-Host 'Lock period ended. Prefer SSH: ssh Administrator@104.194.140.203' -ForegroundColor Green
