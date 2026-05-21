import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { ForwardDemoEvent, ForwardDemoEventType } from './types';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_DIR = path.join(__dirname, 'data');
const LOG_FILE = path.join(LOG_DIR, 'forward-demo-log.jsonl');

function ensureDir(): void {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
}

export function forwardDemoLogPath(): string {
  return LOG_FILE;
}

export function appendForwardDemoEvent(event: Omit<ForwardDemoEvent, 'id'> & { id?: string }): ForwardDemoEvent {
  ensureDir();
  const row: ForwardDemoEvent = {
    ...event,
    id: event.id ?? `evt_${event.tsMs}_${Math.random().toString(36).slice(2, 9)}`,
  };
  fs.appendFileSync(LOG_FILE, `${JSON.stringify(row)}\n`, 'utf8');
  return row;
}

export function loadForwardDemoEvents(sinceMs = 0): ForwardDemoEvent[] {
  if (!fs.existsSync(LOG_FILE)) return [];
  const lines = fs.readFileSync(LOG_FILE, 'utf8').split('\n').filter(Boolean);
  const out: ForwardDemoEvent[] = [];
  for (const line of lines) {
    try {
      const e = JSON.parse(line) as ForwardDemoEvent;
      if (e.tsMs >= sinceMs) out.push(e);
    } catch {
      /* skip corrupt */
    }
  }
  return out.sort((a, b) => a.tsMs - b.tsMs);
}

export function filterEvents(
  events: ForwardDemoEvent[],
  opts?: { types?: ForwardDemoEventType[]; sinceMs?: number; untilMs?: number }
): ForwardDemoEvent[] {
  return events.filter((e) => {
    if (opts?.types && !opts.types.includes(e.type)) return false;
    if (opts?.sinceMs != null && e.tsMs < opts.sinceMs) return false;
    if (opts?.untilMs != null && e.tsMs > opts.untilMs) return false;
    return true;
  });
}

export function clearForwardDemoLog(): void {
  if (fs.existsSync(LOG_FILE)) fs.unlinkSync(LOG_FILE);
}
