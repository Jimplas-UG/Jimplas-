import * as fs from 'node:fs';
import * as path from 'node:path';

export type SafetyState = {
  nyDay: string | null;
  dayStartEquity: number;
  peakEquity: number;
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
      return normalizeSafetyState(JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) as Partial<SafetyState>);
    }
  } catch {
    /* fresh */
  }
  return freshSafetyState();
}

function freshSafetyState(): SafetyState {
  return {
    nyDay: null,
    dayStartEquity: 0,
    peakEquity: 0,
    consecutiveApiFailures: 0,
    failsafe: false,
    failsafeReason: null,
    lastExecutedBarT: null,
    lastOrderIdempotencyKey: null,
  };
}

/** Normalize state loaded from disk (older files may omit peakEquity). */
export function normalizeSafetyState(raw: Partial<SafetyState>): SafetyState {
  const base = freshSafetyState();
  return {
    nyDay: raw.nyDay ?? base.nyDay,
    dayStartEquity: Number(raw.dayStartEquity) || 0,
    peakEquity: Number(raw.peakEquity) || 0,
    consecutiveApiFailures: Number(raw.consecutiveApiFailures) || 0,
    failsafe: Boolean(raw.failsafe),
    failsafeReason: raw.failsafeReason ?? null,
    lastExecutedBarT: raw.lastExecutedBarT ?? null,
    lastOrderIdempotencyKey: raw.lastOrderIdempotencyKey ?? null,
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
    s.peakEquity = equity;
  }
  if (s.dayStartEquity <= 0) s.dayStartEquity = equity;
}

/** NY-day roll + running peak for drawdown gates. */
export function updateEquityTracking(s: SafetyState, ymd: string, equity: number): void {
  rollDayIfNeeded(s, ymd, equity);
  if (s.peakEquity <= 0 || equity > s.peakEquity) s.peakEquity = equity;
}

/** Env FORWARD_DRY_RUN=1 (default) blocks all live orders. */
export function envDryRunEnabled(): boolean {
  const v = (process.env.FORWARD_DRY_RUN ?? '1').trim().toLowerCase();
  return v === '1' || v === 'true' || v === 'yes';
}

export function appendSafetyLog(message: string, extra: Record<string, unknown> = {}): void {
  const dir = path.dirname(STATE_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const line =
    JSON.stringify({ ts: new Date().toISOString(), event: 'safety', message, ...extra }) + '\n';
  fs.appendFileSync(path.join(dir, 'safety.jsonl'), line, 'utf8');
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
