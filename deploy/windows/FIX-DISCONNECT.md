# Fix: "Another connection was made" (RDP kicked off)

## Cause on YOUR PC (most likely)
A hidden **mstsc.exe** was still running from earlier deploy attempts.
That counts as a second RDP login and kicks you off.

**Run before every RDP:**
```powershell
cd c:\Users\Amoskole\bsv3\deploy\windows
.\STOP-RDP-CONFLICTS.ps1
Start-Sleep -Seconds 90
```
Then connect RDP **once**.

## Do NOT use (opens competing RDP)
- `rdp-auto-install.ps1`
- `move-to-vps-only.ps1`
- `rdp-session-deploy.ps1`
- Any Cursor agent "open RDP for you"

## Best fix: never use RDP for install
```powershell
$env:VPS_PW = 'panel-password'
.\GODMODE-SSH-DEPLOY.ps1
```

## On the VPS (one quick RDP after SSH works)
Block RDP from internet except your IP — then only you can connect:
```powershell
# Administrator — replace YOUR.IP.HERE
New-NetFirewallRule -DisplayName 'RDP-Only-Me' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -RemoteAddress YOUR.IP.HERE
New-NetFirewallRule -DisplayName 'RDP-Block-Others' -Direction Inbound -Action Block -Protocol TCP -LocalPort 3389 -RemoteAddress Any -ErrorAction SilentlyContinue
```

## Hosting panel
- **Close** the browser VPS console tab completely
- Only then use Remote Desktop

## If it still happens
- Someone has your password (rotate again)
- Provider auto-reconnect console — ask support
- Brute RDP on 3389 — restrict 3389 to your IP in cloud firewall
