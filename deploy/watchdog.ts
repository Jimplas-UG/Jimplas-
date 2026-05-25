/**
 * Production watchdog — polls services, auto-restarts on failure, resets bot failsafe.
 * Runs via Bilshenz-Watchdog scheduled task.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { execSync } from 'node:child_process';

const DESK = process.env.DESK_HEALTH_URL ?? 'http://127.0.0.1:8791/health';
const MT5 = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const INTERVAL_MS = Number(process.env.WATCHDOG_INTERVAL_MS ?? 60_000);
const LOG_DIR = process.env.TRADINGBOT_LOG_DIR ?? 'C:\\logs\\tradingbot';
const SAFETY_FILE = process.env.SAFETY_STATE_PATH ?? path.join(LOG_DIR, 'safety-state.json');

const MT5_TERMINAL_PATH = process.env.MT5_TERMINAL_PATH ?? 'C:\\Program Files\\MetaTrader 5 Exness';

let prevDesk = true;
let prevMt5 = true;
let deskDownCount = 0;
let mt5DownCount = 0;
const RESTART_AFTER = 3;

function log(msg: string): void {
  const ts = new Date().toISOString();
  const line = `${ts} [watchdog] ${msg}`;
  console.log(line);
  try {
    fs.appendFileSync(path.join(LOG_DIR, 'watchdog.log'), line + '\n', 'utf8');
  } catch { /* ignore */ }
}

function logReconnect(message: string, extra: Record<string, unknown> = {}): void {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  const line =
    JSON.stringify({ ts: new Date().toISOString(), event: 'reconnect', message, ...extra }) + '\n';
  fs.appendFileSync(path.join(LOG_DIR, 'reconnect.jsonl'), line, 'utf8');
}

function runPs(cmd: string, timeoutMs = 90_000): string {
  try {
    return execSync(`powershell -NoProfile -Command "${cmd}"`, { timeout: timeoutMs, encoding: 'utf8' }).trim();
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

async function probe(url: string): Promise<{ ok: boolean; detail: string }> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });
    const text = await res.text();
    let ok = res.ok;
    if (url.includes('/api/status') && res.ok) {
      try {
        const j = JSON.parse(text) as { connected?: boolean };
        ok = Boolean(j.connected);
      } catch { ok = false; }
    }
    return { ok, detail: text.slice(0, 200) };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

function ensureTerminal64(): void {
  try {
    const result = runPs("(Get-Process terminal64 -ErrorAction SilentlyContinue).Id");
    if (result && result.match(/\d+/)) return;
    const exe = `${MT5_TERMINAL_PATH}\\terminal64.exe`;
    const check = runPs(`Test-Path '${exe}'`);
    if (check.toLowerCase() !== 'true') {
      log(`terminal64.exe not found at ${exe}`);
      return;
    }
    log('terminal64 not running — starting with /algotrading...');
    runPs(`Start-Process '${exe}' -ArgumentList '/algotrading'`);
    logReconnect('terminal64 started by watchdog', { service: 'terminal64' });
  } catch (e) {
    log(`ensureTerminal64 error: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function resetBotFailsafe(): void {
  try {
    if (!fs.existsSync(SAFETY_FILE)) return;
    const state = JSON.parse(fs.readFileSync(SAFETY_FILE, 'utf8'));
    if (state.failsafe || state.consecutiveApiFailures >= 6) {
      state.consecutiveApiFailures = 0;
      state.failsafe = false;
      state.failsafeReason = null;
      fs.writeFileSync(SAFETY_FILE, JSON.stringify(state, null, 2), 'utf8');
      log('Reset bot failsafe — MT5 is healthy again');
    }
  } catch { /* ignore */ }
}

async function tick(): Promise<void> {
  ensureTerminal64();

  const desk = await probe(DESK);
  const mt5 = await probe(`${MT5}/api/status`);

  if (!desk.ok) {
    deskDownCount++;
    if (prevDesk) {
      logReconnect('desk-api down', { service: 'desk-api' });
      log(`desk-api DOWN: ${desk.detail}`);
    }
    if (deskDownCount >= RESTART_AFTER) {
      log('Restarting Bilshenz-DeskAPI...');
      runPs("Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Start-Sleep 3; Start-ScheduledTask -TaskName 'Bilshenz-DeskAPI'");
      deskDownCount = 0;
    }
  } else {
    if (!prevDesk) {
      logReconnect('desk-api recovered', { service: 'desk-api' });
      log('desk-api recovered');
    }
    deskDownCount = 0;
  }

  if (!mt5.ok) {
    mt5DownCount++;
    if (prevMt5) {
      logReconnect('mt5-api disconnected', { service: 'mt5-api', detail: mt5.detail });
      log(`MT5 DOWN: ${mt5.detail}`);
    }
    if (mt5DownCount >= RESTART_AFTER) {
      log('MT5 down for 3 checks — full restart (terminal64 + Python API)...');
      // Kill Python API
      runPs("Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue");
      // Kill terminal64 (IPC pipe is dead, process is a zombie)
      runPs("taskkill /f /im terminal64.exe 2>$null");
      log('Killed terminal64 + python. Waiting 10s...');
      // Synchronous wait before restart
      runPs("Start-Sleep 10");
      // Start terminal64 fresh with /algotrading
      const exe = `${MT5_TERMINAL_PATH}\\terminal64.exe`;
      runPs(`Start-Process '${exe}' -ArgumentList '/algotrading'`);
      log('terminal64 started. Waiting 60s for full init...');
      // Wait for terminal to fully initialize (critical — needs 60s on VPS)
      runPs("Start-Sleep 60");
      // Now start the Python API
      runPs("Start-ScheduledTask -TaskName 'Bilshenz-MT5-API'");
      log('MT5 API task started. Waiting 15s for API to come up...');
      runPs("Start-Sleep 15");
      logReconnect('full MT5 stack restarted by watchdog', { service: 'mt5-full' });
      mt5DownCount = 0;
    }
  } else {
    if (!prevMt5) {
      logReconnect('mt5-api connected', { service: 'mt5-api' });
      log('MT5 recovered');
      resetBotFailsafe();
    }
    mt5DownCount = 0;
    resetBotFailsafe();
  }

  const ts = new Date().toISOString().slice(11, 19);
  console.log(`${ts} desk=${desk.ok} mt5=${mt5.ok}${!mt5.ok ? ' ' + mt5.detail.slice(0, 80) : ''}`);

  prevDesk = desk.ok;
  prevMt5 = mt5.ok;
}

async function main(): Promise<void> {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  log(`Started — desk=${DESK} mt5=${MT5}/api/status interval=${INTERVAL_MS}ms`);
  await tick();
  setInterval(() => void tick(), INTERVAL_MS);
}

void main();
