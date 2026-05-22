# Run on YOUR PC before RDP - stops Cursor/automation from stealing your VPS session
Get-Process mstsc -ErrorAction SilentlyContinue | Stop-Process -Force
cmdkey /delete:TERMSRV/104.194.140.203 2>$null | Out-Null
Write-Host 'OK: mstsc closed, saved VPS password removed from Windows Credential Manager.'
Write-Host 'Wait 60 seconds, then connect RDP ONCE with new password from panel.'
