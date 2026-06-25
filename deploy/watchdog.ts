/**
 * Production watchdog — polls services, auto-restarts on failure, resets bot failsafe.
 * Runs via Bilshenz-Watchdog scheduled task.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { execSync } from 'node:child_process';

const DESK = process.env.DESK_HEALTH_URL ?? 'http://127.0.0.1:8791/health';
const BINANCE = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const INTERVAL_MS = Number(process.env.WATCHDOG_INTERVAL_MS ?? 60_000);
const LOG_DIR = process.env.TRADINGBOT_LOG_DIR ?? 'C:\\logs\\tradingbot';
const SAFETY_FILE = process.env.SAFETY_STATE_PATH ?? path.join(LOG_DIR, 'safety-state.json');

let prevDesk = true;
let prevBroker = true;
let deskDownCount = 0;
let brokerDownCount = 0;
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
    if (res.ok) {
      try {
        const j = JSON.parse(text) as { connected?: boolean; ok?: boolean };
        ok = url.includes('/health') ? Boolean(j.ok ?? true) : Boolean(j.connected);
      } catch { ok = false; }
    }
    return { ok, detail: text.slice(0, 200) };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
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
      log('Reset bot failsafe — broker is healthy again');
    }
  } catch { /* ignore */ }
}

function restartBrokerTask(): void {
  log('Restarting Bilshenz-Binance-API...');
  runPs("Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Start-Sleep 3; Start-ScheduledTask -TaskName 'Bilshenz-Binance-API'");
  logReconnect('binance-api restarted by watchdog', { service: 'binance-api' });
}

async function tick(): Promise<void> {
  const desk = await probe(DESK);
  const broker = await probe(`${BINANCE}/health`);

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

  if (!broker.ok) {
    brokerDownCount++;
    if (prevBroker) {
      logReconnect('binance-api disconnected', { service: 'binance-api', detail: broker.detail });
      log(`Binance DOWN: ${broker.detail}`);
    }
    if (brokerDownCount >= RESTART_AFTER) {
      restartBrokerTask();
      brokerDownCount = 0;
    }
  } else {
    if (!prevBroker) {
      logReconnect('binance-api connected', { service: 'binance-api' });
      log('Binance recovered');
      resetBotFailsafe();
    }
    brokerDownCount = 0;
    resetBotFailsafe();
  }

  if (desk.ok && broker.ok) {
    try {
      if (fs.existsSync(SAFETY_FILE)) {
        const state = JSON.parse(fs.readFileSync(SAFETY_FILE, 'utf8'));
        if (state.failsafe || state.consecutiveApiFailures > 0) {
          state.consecutiveApiFailures = 0;
          state.failsafe = false;
          state.failsafeReason = null;
          fs.writeFileSync(SAFETY_FILE, JSON.stringify(state, null, 2), 'utf8');
          log('Cleared bot failsafe + API failure counter — both services healthy');
        }
      }
    } catch { /* ignore */ }
  }

  try {
    const botCheck = runPs(
      "Get-Process node -ErrorAction SilentlyContinue | " +
      "Where-Object { (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.Id)).CommandLine -match 'run-forward-demo' } | " +
      "Select-Object -First 1 -ExpandProperty Id"
    );
    if (!botCheck || !botCheck.match(/\d+/)) {
      log('Forward bot process not found — restarting Bilshenz-ForwardBot...');
      runPs("Start-ScheduledTask -TaskName 'Bilshenz-ForwardBot'");
      logReconnect('forward bot restarted by watchdog', { service: 'forward-bot' });
    }
  } catch { /* ignore */ }

  const ts = new Date().toISOString().slice(11, 19);
  console.log(`${ts} desk=${desk.ok} binance=${broker.ok}${!broker.ok ? ' ' + broker.detail.slice(0, 80) : ''}`);

  prevDesk = desk.ok;
  prevBroker = broker.ok;
}

async function main(): Promise<void> {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  log(`Started — desk=${DESK} binance=${BINANCE} interval=${INTERVAL_MS}ms`);
  await tick();
  setInterval(() => void tick(), INTERVAL_MS);
}

void main();
