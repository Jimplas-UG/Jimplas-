# Fresh deployment (clean slate)

**Full guide:** [DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md) · **One-shot on VPS:** `.\master-deploy.ps1`

## 1) Reset (already done on your PC if you ran RESET-LOCAL)

**Your PC:**
```powershell
cd c:\Users\Amoskole\bsv3\deploy\windows
.\RESET-LOCAL-DEPLOYMENT.ps1
```

**VPS** (web console or one RDP — paste whole file):
```powershell
# Copy contents of RESET-VPS-DEPLOYMENT.ps1 and run on VPS
```

## 2) Cloud panel
- VPS: Windows, IP `104.194.140.203`
- Firewall: allow **22** (SSH) and/or **3389** (RDP) from **your IP only**
- Rotate VPS password if it was ever shared in chat

## 3) Deploy to VPS (pick one)

### A — SSH (best, no RDP kicks)
```powershell
$env:VPS_PW = 'panel-password-here'   # this terminal only
cd c:\Users\Amoskole\bsv3\deploy\windows
.\GODMODE-SSH-DEPLOY.ps1
```

### B — One RDP session + bundle
```powershell
.\EXPERT-DEPLOY.ps1
# Then on VPS run EXPERT-VPS-RUN.ps1 from Desktop / tsclient
```

### C — Web console only
Paste `CONSOLE-PASTE-INSTALL.ps1` in provider console (no RDP app).

## 4) On VPS after code is installed
1. Install **MetaTrader 5 Exness**, login, **XAUUSD**
2. `notepad C:\ProgramData\Bilshenz\tradingbot.env` — set `DESK_API_KEY`, then `FORWARD_DRY_RUN=0` when ready
3. `C:\opt\bilshenz\deploy\windows\start-bot.ps1`
4. `C:\opt\bilshenz\deploy\windows\health-check.ps1`

## Rules
- **One** remote session at a time (RDP *or* console, not both)
- Cursor/agents: do not auto-open RDP (`AGENTS-NO-RDP.md`)
- Secrets only in `C:\ProgramData\Bilshenz\tradingbot.env` on the VPS
