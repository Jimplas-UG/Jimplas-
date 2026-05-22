# Windows VPS — full MT5 XAUUSD deployment guide

**Architecture:** MetaTrader 5 (broker-branded) + Python API `:8765` + Node forward bot + desk API `:8791` + watchdog. **Not** an MQL5 EA on-chart bot.

**Secrets:** only `C:\ProgramData\Bilshenz\tradingbot.env` — never in git.

**Critical:** Keep **one interactive RDP session logged in**. MT5 Python IPC does not work headless as SYSTEM.

---

## Quick path (experienced)

```powershell
# Administrator PowerShell on VPS
cd C:\opt\bilshenz\deploy\windows
.\master-deploy.ps1 -InstallMt5 Exness
notepad C:\ProgramData\Bilshenz\tradingbot.env
.\start-bot.ps1
.\validate-deployment.ps1
```

---

## Phase 1 — System validation

```powershell
.\phase1-system-prep.ps1
```

Configures: timezone, no sleep/hibernate, high-performance power, Windows Update no forced reboot, log dirs.

**Validate only (no changes):**

```powershell
.\phase1-system-prep.ps1 -ValidateOnly
```

| Check | Pass |
|-------|------|
| Windows 64-bit | `PHASE1_OK` |
| Internet + DNS | |
| RDP service + firewall | |
| Outbound firewall Allow | |

---

## Phase 2 — Python + Node

Handled by `production-setup.ps1` (Python 3.12, Node LTS, venv, `npm ci`).

```powershell
.\validate-python-env.ps1
```

---

## Phase 3 — MT5 installation

Use **broker-branded** MT5 (generic MetaQuotes build often breaks Python IPC).

```powershell
cd C:\opt\bilshenz\mt5_trading_system
.\install-mt5-broker.ps1 -Broker Exness
```

**Manual steps in MT5:**

1. Complete installer wizard
2. **File → Login to trade account** (your credentials — not stored in repo)
3. **Market Watch → XAUUSD** → open M15/H1 chart → confirm ticks
4. **File → Open Data Folder** → parent folder = `MT5_TERMINAL_PATH` in env

**Login fails?**

| Symptom | Fix |
|---------|-----|
| Invalid account | Check login number, password, **exact server name** from broker |
| Server not found | Install correct broker MT5; demo server differs from live |
| No XAUUSD | Broker symbol may be `XAUUSDm` — update `MT5_SYMBOL` in env |

```powershell
.\validate-mt5.ps1
```

---

## Phase 4 — Bot deployment

```powershell
# Env (first time)
Copy-Item .\tradingbot.env.example C:\ProgramData\Bilshenz\tradingbot.env
notepad C:\ProgramData\Bilshenz\tradingbot.env

# Register 24/7 tasks + start
.\install-scheduled-tasks.ps1
.\start-bot.ps1
.\health-check.ps1
```

**Services:**

| Task | Role |
|------|------|
| Bilshenz-MT5-API | Python bridge → MT5 |
| Bilshenz-DeskAPI | Desk API :8791 |
| Bilshenz-ForwardBot | Strategy / signals |
| Bilshenz-Watchdog | Health poll |

**Dry run (default):** `FORWARD_DRY_RUN=1` — signals only, no orders.

---

## Phase 5 — Auto-recovery

```powershell
.\install-mt5-terminal-task.ps1
.\install-scheduled-tasks.ps1   # bot processes: restart every 1 min on failure
.\install-log-rotation.ps1      # daily 03:00, 14-day retention
```

| Layer | Behavior |
|-------|----------|
| MT5 terminal task | Start at logon; restart if `terminal64` crashed |
| Bot scheduled tasks | Restart on failure (999 retries, 1 min interval) |
| `fetchRetry.ts` | Exponential backoff on HTTP errors |
| `safetyControls.ts` | Duplicate order prevention, API failure failsafe |

**Broker disconnect:** Watchdog logs alerts; forward bot records API failures → failsafe after `MAX_API_FAILURES`.

---

## Phase 6 — Logging

| File | Content |
|------|---------|
| `forward-bot.log` | Human-readable bot log |
| `trades.jsonl` | Executed / dry-run trades |
| `errors.jsonl` | Errors |
| `reconnect.jsonl` | MT5/API reconnect events |
| `safety.jsonl` | Failsafe triggers |
| `watchdog.log` | Health poll |
| `mt5-api.log` | Python bridge |

```powershell
Get-Content C:\logs\tradingbot\forward-bot.log -Wait -Tail 30
Get-Content C:\logs\tradingbot\trades.jsonl -Wait -Tail 20
```

---

## Phase 7 — Risk safety

Set in `tradingbot.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_DAILY_LOSS_PCT` | 3 | Stop after daily loss % |
| `MAX_DAILY_TRADES` | 3 | Cap trades per NY day |
| `MAX_API_FAILURES` | 8 | Failsafe after repeated API errors |
| `FORWARD_DRY_RUN` | 1 | `1` = no real orders |

**Emergency halt:** set `FORWARD_DRY_RUN=1` and `.\stop-bot.ps1`

**Clear failsafe:** delete `C:\logs\tradingbot\safety-state.json` or set `"failsafe": false` after review.

---

## Phase 8 — Operations

| Action | Command |
|--------|---------|
| Start | `.\start-bot.ps1` |
| Stop | `.\stop-bot.ps1` |
| Restart | `.\restart-bot.ps1` |
| Health | `.\health-check.ps1` |
| Full validate | `.\validate-deployment.ps1` |
| Go live | Set `FORWARD_DRY_RUN=0` in env → `.\restart-bot.ps1` |
| Emergency halt | `.\emergency-halt.ps1` |

See also [OPERATIONS.md](./OPERATIONS.md).

---

## Deploy from your PC to VPS

| Method | Script |
|--------|--------|
| SSH | `GODMODE-SSH-DEPLOY.ps1` |
| Bundle + RDP | `EXPERT-DEPLOY.ps1` → VPS: `EXPERT-VPS-RUN.ps1` |
| Console paste | `CONSOLE-PASTE-INSTALL.ps1` |

Fresh slate: [FRESH-START.md](./FRESH-START.md)
