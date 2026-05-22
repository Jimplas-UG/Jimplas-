# VPS access — stop disconnect loop

## What was wrong
- Hidden **mstsc** on your PC + **public RDP (3389)** on the internet = constant "another connection" kicks.
- Cursor **no longer** opens RDP (scripts `rdp*.ps1` disabled).

## Your 3 steps (no sadness RDP loop)

### A) On your PC (PowerShell)
```powershell
cd c:\Users\Amoskole\bsv3\deploy\windows
.\KILL-ALL-RDP-LOCAL.ps1
Start-Job { & "$using:PWD\LOCK-NO-RDP.ps1" -Minutes 45 }  # blocks mstsc 45 min
```

### B) Hosting panel (browser) — NOT Remote Desktop
VPS → **Console** / **View console** → paste all of **CONSOLE-PASTE-INSTALL.ps1** → Enter.

### C) Cloud firewall (provider website)
- **Allow** TCP **22** (SSH)
- **Deny** TCP **3389** from everyone (or allow only your home IP)

### D) From PC — SSH only (after B finishes)
```powershell
ssh Administrator@104.194.140.203
```
Install MT5 Exness on VPS through SSH session or download MT5 installer via SSH browser.

## After that
Bot runs on VPS only. Your PC does not need RDP open ever.
