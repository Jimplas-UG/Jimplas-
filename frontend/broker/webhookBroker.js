import { TRADING_SYMBOL } from '../lib/tradingSymbol';

function trimSnippet(s, max = 400) {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

export async function postBrokerOrderWebhook(intent, opts) {
  const url =
    opts?.url?.trim() ||
    (typeof process !== 'undefined' ? process.env?.EXPO_PUBLIC_BROKER_WEBHOOK_URL : '') ||
    '';
  if (!url) {
    return { ok: false, status: 0, bodySnippet: 'No broker webhook URL configured' };
  }
  const secret =
    opts?.secret?.trim() ||
    (typeof process !== 'undefined' ? process.env?.EXPO_PUBLIC_BROKER_WEBHOOK_SECRET : '') ||
    '';

  const headers = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  };
  if (secret) headers.Authorization = `Bearer ${secret}`;

  let last = { ok: false, status: 0, bodySnippet: '' };

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

export function buildBrokerOrderIntent(trade, opts) {
  if (trade.side !== 'BUY' && trade.side !== 'SELL') return null;
  const setup = trade.setup === 'P1' || trade.setup === 'P2' || trade.setup === 'P3' ? trade.setup : 'NONE';
  const intentAtIso = new Date().toISOString();
  const barTimeIso = opts.barTimeMs != null ? new Date(opts.barTimeMs).toISOString() : null;
  return {
    source: 'bilshenz_v3',
    intentAtIso,
    symbol: opts.symbol?.trim() || TRADING_SYMBOL,
    side: trade.side,
    setup,
    entry: trade.entry,
    sl: trade.sl,
    tp1: trade.tp1,
    tp2: null,
    confidencePct: Number.isFinite(trade.confidencePct) ? trade.confidencePct : null,
    barTimeIso,
    lots: opts.lots ?? null,
    quantity: opts.quantity ?? null,
  };
}
