# Windows VPS — trading bot operations

All secrets live in **`C:\ProgramData\Bilshenz\tradingbot.env`** (never in git).

**New VPS from scratch:** see [DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md) (Phases 1–8).

## One-time setup (Administrator PowerShell)

```powershell
cd C:\opt\bilshenz   # or your clone path
.\deploy\windows\production-setup.ps1
```

Then:

1. Open **MetaTrader 5 Exness** → log in → add **XAUUSD** to Market Watch.
2. Edit env: `notepad C:\ProgramData\Bilshenz\tradingbot.env`
   - Set `DESK_API_KEY` (long random string)
   - Keep `FORWARD_DRY_RUN=1` until health checks pass
   - Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. `.\deploy\windows\start-bot.ps1`
4. `.\deploy\windows\health-check.ps1`

## Start / stop / restart

```powershell
.\deploy\windows\start-bot.ps1
.\deploy\windows\stop-bot.ps1
.\deploy\windows\restart-bot.ps1
```

**Backup runtime** (minimized PowerShell windows):

```powershell
.\deploy\windows\start-bot.ps1 -BackupOnly
```

## Live logs

```powershell
Get-Content C:\logs\tradingbot\forward-bot.log -Wait -Tail 30
Get-Content C:\logs\tradingbot\trades.jsonl -Wait -Tail 20
Get-Content C:\logs\tradingbot\errors.jsonl -Wait -Tail 20
Get-Content C:\logs\tradingbot\reconnect.jsonl -Wait -Tail 20
```

## Emergency halt

```powershell
.\deploy\windows\emergency-halt.ps1
```

Stops all tasks, sets `FORWARD_DRY_RUN=1`, enables failsafe. Clear failsafe only after manual review.

## Go live (after demo validation)

In `tradingbot.env`:

```
FORWARD_DRY_RUN=0
```

Then: `.\deploy\windows\restart-bot.ps1`

## Safety controls (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_DAILY_LOSS_PCT` | 3 | Stop new trades after daily loss % |
| `MAX_DAILY_TRADES` | 3 | Cap trades per NY day |
| `MAX_API_FAILURES` | 8 | Failsafe after repeated API errors |
| `FORWARD_DRY_RUN` | 1 | 1 = signals only, no orders |

Clear failsafe: delete `C:\logs\tradingbot\safety-state.json` or set `"failsafe": false`.

## 24/7 confirmation

```powershell
.\deploy\windows\health-check.ps1
Get-ScheduledTask Bilshenz-* | Format-Table TaskName, State
```

Tasks should be **Running** or **Ready**; `desk-api` and `mt5-api` health should be up; MT5 `connected=true`.

## Architecture (single Windows VPS)

```
MT5 Terminal (Exness) ←→ Python API :8765 ←→ Forward Bot
                              ↑
                         Desk API :8791
                         Watchdog (health poll)
```

Logs: `C:\logs\tradingbot\` — rotated daily at 03:00 (14-day retention).
