# Windows VPS deployment

Use this folder on a **Windows Server/VPS** where **MT5 + bot run on the same machine** (recommended).

| Script | Purpose |
|--------|---------|
| **`DEPLOYMENT-GUIDE.md`** | **Full 8-phase deploy guide (start here)** |
| `master-deploy.ps1` | One-shot: phase1 + setup + MT5 terminal tasks |
| `phase1-system-prep.ps1` | 24/7 OS tuning + validation |
| `production-setup.ps1` | Git, Node, Python, env, firewall, scheduled tasks |
| `validate-deployment.ps1` | End-to-end smoke test |
| `start-bot.ps1` / `stop-bot.ps1` / `restart-bot.ps1` | Control 24/7 services |
| `health-check.ps1` | Safe status (no secrets printed) |
| `OPERATIONS.md` | Day-2 runbook |

Secrets: `C:\ProgramData\Bilshenz\tradingbot.env` only.

For **Ubuntu** VPS + Windows MT5 bridge, see `deploy/OPERATIONS.md` instead.
