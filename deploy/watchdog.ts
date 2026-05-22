/**
 * Polls desk-api /health and MT5 /api/status; logs reconnect transitions to reconnect.jsonl.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

const DESK = process.env.DESK_HEALTH_URL ?? 'http://127.0.0.1:8791/health';
const MT5 = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const INTERVAL_MS = Number(process.env.WATCHDOG_INTERVAL_MS ?? 60_000);
const LOG_DIR = process.env.TRADINGBOT_LOG_DIR ?? 'C:\\logs\\tradingbot';

let prevDesk = true;
let prevMt5 = true;

function logReconnect(message: string, extra: Record<string, unknown> = {}): void {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  const line =
    JSON.stringify({ ts: new Date().toISOString(), event: 'reconnect', message, ...extra }) + '\n';
  fs.appendFileSync(path.join(LOG_DIR, 'reconnect.jsonl'), line, 'utf8');
}

async function check(url: string): Promise<{ ok: boolean; detail: string }> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const text = await res.text();
    let ok = res.ok;
    if (url.includes('/api/status') && res.ok) {
      try {
        const j = JSON.parse(text) as { connected?: boolean };
        ok = Boolean(j.connected);
      } catch {
        ok = false;
      }
    }
    return { ok, detail: text.slice(0, 200) };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

async function tick(): Promise<void> {
  const ts = new Date().toISOString();
  const desk = await check(DESK);
  const mt5 = await check(`${MT5}/api/status`);
  const line = `${ts} desk=${desk.ok} mt5=${mt5.ok} ${!mt5.ok ? mt5.detail : ''}`;
  console.log(line);

  if (!desk.ok && prevDesk) {
    logReconnect('desk-api down', { service: 'desk-api' });
    console.error('ALERT: desk-api down');
  }
  if (desk.ok && !prevDesk) logReconnect('desk-api recovered', { service: 'desk-api' });

  if (!mt5.ok && prevMt5) {
    logReconnect('mt5-api disconnected', { service: 'mt5-api', detail: mt5.detail });
    console.error('ALERT: MT5 API unreachable — ensure MT5 terminal logged in');
  }
  if (mt5.ok && !prevMt5) logReconnect('mt5-api connected', { service: 'mt5-api' });

  prevDesk = desk.ok;
  prevMt5 = mt5.ok;
}

async function main(): Promise<void> {
  console.log(`Watchdog started desk=${DESK} mt5=${MT5}/api/status logDir=${LOG_DIR}`);
  await tick();
  setInterval(() => void tick(), INTERVAL_MS);
}

void main();
