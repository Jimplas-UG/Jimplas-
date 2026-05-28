/**
 * Publish BSv3.2 / forward-bot events to JCM supervisory platform ingest webhook.
 * Env: JCM_INGEST_WEBHOOK_URL, JCM_WEBHOOK_SECRET (or EVENT_WEBHOOK_SECRET)
 */

const JCM_URL = (process.env.JCM_INGEST_WEBHOOK_URL ?? '').trim();
const JCM_SECRET = (
  process.env.JCM_WEBHOOK_SECRET ?? process.env.EVENT_WEBHOOK_SECRET ?? ''
).trim();

export function jcmWebhookConfigured(): boolean {
  return JCM_URL.length > 0;
}

export async function publishJcmEvent(
  eventType: string,
  payload: Record<string, unknown>
): Promise<boolean> {
  if (!JCM_URL) return false;
  try {
    const res = await fetch(JCM_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Webhook-Secret': JCM_SECRET,
      },
      body: JSON.stringify({ event_type: eventType, payload }),
    });
    if (!res.ok) {
      const snippet = (await res.text()).slice(0, 200);
      console.error(`[jcm] ${eventType} HTTP ${res.status}: ${snippet}`);
      return false;
    }
    return true;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[jcm] ${eventType} failed: ${msg}`);
    return false;
  }
}

function newEventId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export async function publishTradeExecuted(opts: {
  symbol: string;
  direction: 'long' | 'short';
  lotSize: number;
  entryPrice: number | null;
  filledPrice?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  setup?: string;
  barTimeMs: number;
  filterStates?: Record<string, string>;
  filtersPassed?: string[];
  marketRegime?: string;
  tradingSession?: string;
  bsv32Confidence?: number;
  mt5Connected?: boolean;
}): Promise<boolean> {
  return publishJcmEvent('trade_executed', {
    event_id: newEventId('bilshenz-exec'),
    event_type: 'trade_executed',
    symbol: opts.symbol,
    direction: opts.direction,
    lot_size: opts.lotSize,
    entry_price: opts.entryPrice,
    filled_price: opts.filledPrice ?? opts.entryPrice,
    stop_loss: opts.stopLoss,
    take_profit: opts.takeProfit,
    outcome: 'open',
    filter_states: opts.filterStates ?? {},
    filters_passed: opts.filtersPassed ?? [],
    market_regime: opts.marketRegime ?? 'unknown',
    trading_session: opts.tradingSession ?? 'off_session',
    bsv32_confidence: opts.bsv32Confidence,
    bsv32_version: '3.2',
    vps_health: {
      mt5_connected: opts.mt5Connected ?? true,
    },
    raw_payload: { setup: opts.setup, bar_time_ms: opts.barTimeMs },
  });
}

export async function publishTradeBlocked(opts: {
  symbol: string;
  direction?: string | null;
  blockedBy: string[];
  filterStates?: Record<string, string>;
  marketRegime?: string;
  tradingSession?: string;
}): Promise<boolean> {
  return publishJcmEvent('trade_blocked', {
    event_id: newEventId('bilshenz-block'),
    symbol: opts.symbol,
    direction: opts.direction,
    blocked_by: opts.blockedBy,
    filter_states: opts.filterStates ?? {},
    market_regime: opts.marketRegime ?? 'unknown',
    trading_session: opts.tradingSession ?? 'off_session',
  });
}

export async function publishSystemState(opts: {
  mt5Connected: boolean;
  deskApiOk: boolean;
  forwardBotOk?: boolean;
  accountEquity?: number;
  openPositions?: number;
  dryRun?: boolean;
}): Promise<boolean> {
  return publishJcmEvent('system_state', {
    bsv32_status: opts.dryRun ? 'dry_run' : 'running',
    mt5_connected: opts.mt5Connected,
    desk_api_ok: opts.deskApiOk,
    forward_bot_ok: opts.forwardBotOk ?? true,
    watchdog_api_ok: true,
    open_positions: opts.openPositions ?? 0,
    account_equity: opts.accountEquity,
    market_regime: 'unknown',
    system_running: opts.mt5Connected && opts.deskApiOk,
  });
}
