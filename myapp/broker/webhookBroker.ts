import type { TradeRecommendation } from '../engine/types';
import type { BrokerOrderIntent, BrokerWebhookResult } from './brokerTypes';

function trimSnippet(s: string, max = 400): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

/**
 * POST JSON to your own HTTPS endpoint (Zapier, Cloudflare Worker, MT5 bridge, etc.).
 * Set `EXPO_PUBLIC_BROKER_WEBHOOK_URL` at build time, or pass `url` from app settings.
 * Optional `EXPO_PUBLIC_BROKER_WEBHOOK_SECRET` → sent as `Authorization: Bearer …`.
 */
export async function postBrokerOrderWebhook(
  intent: BrokerOrderIntent,
  opts?: { url?: string; secret?: string }
): Promise<BrokerWebhookResult> {
  const url =
    opts?.url?.trim() ||
    (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_BROKER_WEBHOOK_URL) ||
    '';
  if (!url) {
    return { ok: false, status: 0, bodySnippet: 'No broker webhook URL configured' };
  }
  const secret =
    opts?.secret?.trim() ||
    (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_BROKER_WEBHOOK_SECRET) ||
    '';

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  };
  if (secret) headers.Authorization = `Bearer ${secret}`;

  let last: BrokerWebhookResult = { ok: false, status: 0, bodySnippet: '' };

  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, 400 * attempt));
    }
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(intent),
      });
      const text = await res.text();
      last = { ok: res.ok, status: res.status, bodySnippet: trimSnippet(text || (res.ok ? 'OK' : 'Empty body')) };
      if (res.ok) return last;
      if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
        return last;
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      last = { ok: false, status: 0, bodySnippet: trimSnippet(msg) };
    }
  }

  return last;
}

/** Build JSON body for a webhook bridge (only when `trade.side` is BUY or SELL). */
export function buildBrokerOrderIntent(
  trade: TradeRecommendation,
  opts: { barTimeMs: number | null; runMode: 'live' | 'backtest'; trigger?: 'manual' | 'auto' }
): BrokerOrderIntent | null {
  if (trade.side !== 'BUY' && trade.side !== 'SELL') return null;
  const setup = trade.setup === 'P1' || trade.setup === 'P2' || trade.setup === 'P3' ? trade.setup : 'NONE';
  const intentAtIso = new Date().toISOString();
  const barTimeIso = opts.barTimeMs != null ? new Date(opts.barTimeMs).toISOString() : null;
  return {
    source: 'bilshenz_v3',
    intentAtIso,
    symbol: 'XAUUSD',
    side: trade.side,
    setup,
    entry: trade.entry,
    sl: trade.sl,
    tp1: trade.tp1,
    tp2: null,
    confidencePct: Number.isFinite(trade.confidencePct) ? trade.confidencePct : null,
    barTimeIso,
    runMode: opts.runMode,
    trigger: opts.trigger ?? 'manual',
  };
}
