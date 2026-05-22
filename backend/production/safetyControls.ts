import * as fs from 'node:fs';
import * as path from 'node:path';

export type SafetyState = {
  nyDay: string | null;
  dayStartEquity: number;
  consecutiveApiFailures: number;
  failsafe: boolean;
  failsafeReason: string | null;
  lastExecutedBarT: number | null;
  lastOrderIdempotencyKey: string | null;
};

const DEFAULT_LOG_DIR =
  process.platform === 'win32' ? 'C:\\logs\\tradingbot' : '/var/log/tradingbot';
const STATE_PATH = process.env.SAFETY_STATE_PATH ?? path.join(DEFAULT_LOG_DIR, 'safety-state.json');

const MAX_DAILY_LOSS_PCT = Number(process.env.MAX_DAILY_LOSS_PCT ?? '3');
const MAX_API_FAILURES = Number(process.env.MAX_API_FAILURES ?? '8');
const MAX_DAILY_TRADES = Number(process.env.MAX_DAILY_TRADES ?? '0');

export function maxDailyTradesLimit(frozenDefault: number): number {
  if (MAX_DAILY_TRADES > 0) return Math.min(25, Math.floor(MAX_DAILY_TRADES));
  return frozenDefault;
}

export function loadSafetyState(): SafetyState {
  try {
    if (fs.existsSync(STATE_PATH)) {
      return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) as SafetyState;
    }
  } catch {
    /* fresh */
  }
  return {
    nyDay: null,
    dayStartEquity: 0,
    consecutiveApiFailures: 0,
    failsafe: false,
    failsafeReason: null,
    lastExecutedBarT: null,
    lastOrderIdempotencyKey: null,
  };
}

export function saveSafetyState(s: SafetyState): void {
  const dir = path.dirname(STATE_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(s, null, 2), 'utf8');
}

export function rollDayIfNeeded(s: SafetyState, ymd: string, equity: number): void {
  if (s.nyDay !== ymd) {
    s.nyDay = ymd;
    s.dayStartEquity = equity;
  }
  if (s.dayStartEquity <= 0) s.dayStartEquity = equity;
}

export function dailyLossBreached(s: SafetyState, equity: number): boolean {
  if (MAX_DAILY_LOSS_PCT <= 0 || s.dayStartEquity <= 0) return false;
  const lossPct = ((s.dayStartEquity - equity) / s.dayStartEquity) * 100;
  return lossPct >= MAX_DAILY_LOSS_PCT;
}

export function recordApiSuccess(s: SafetyState): void {
  s.consecutiveApiFailures = 0;
}

export function recordApiFailure(s: SafetyState, reason: string): string | null {
  s.consecutiveApiFailures += 1;
  if (s.consecutiveApiFailures >= MAX_API_FAILURES) {
    s.failsafe = true;
    s.failsafeReason = `API failures (${s.consecutiveApiFailures}): ${reason}`;
    return s.failsafeReason;
  }
  return null;
}

export function isDuplicateOrder(s: SafetyState, barT: number, key: string): boolean {
  if (s.lastExecutedBarT === barT) return true;
  if (s.lastOrderIdempotencyKey === key) return true;
  return false;
}

export function markOrderExecuted(s: SafetyState, barT: number, key: string): void {
  s.lastExecutedBarT = barT;
  s.lastOrderIdempotencyKey = key;
}

export function clearFailsafe(s: SafetyState): void {
  s.failsafe = false;
  s.failsafeReason = null;
  s.consecutiveApiFailures = 0;
}
