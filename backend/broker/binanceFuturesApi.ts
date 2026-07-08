import type { BrokerOrderIntent } from './brokerTypes';
import type { BinanceBar, BinanceOrderResult, BinanceSymbolSpec, BinanceTick } from './binanceTypes';
import { lotsToQuantity, quantityFromRiskUsd } from './quantityMath';
import { normalizeOrderPrices } from './tickUnits';

function trimSnippet(s: string, max = 400): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

function base(baseUrl: string): string {
  return baseUrl.replace(/\/$/, '');
}

function bridgeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  const token = (process.env.BRIDGE_TOKEN ?? '').trim();
  if (token) h['X-Bridge-Token'] = token;
  return h;
}

export async function fetchBinanceConnected(apiBaseUrl: string): Promise<boolean> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/status`, { headers: bridgeHeaders() });
    if (!res.ok) return false;
    const j = await res.json();
    return !!j.connected;
  } catch {
    return false;
  }
}

export async function postBinanceAttach(apiBaseUrl: string, timeoutMs = 15000): Promise<{ ok: boolean; detail?: string }> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/attach`, {
      method: 'POST',
      headers: bridgeHeaders(),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j);
      return { ok: false, detail };
    }
    return { ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, detail: msg };
  }
}

export async function fetchBinanceSymbolSpec(
  apiBaseUrl: string,
  symbol = 'BTCUSDT',
  pipSize = 0.1,
): Promise<BinanceSymbolSpec | null> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/symbol/${encodeURIComponent(symbol)}?pip_size=${pipSize}`, {
      headers: bridgeHeaders(),
    });
    if (!res.ok) return null;
    const j = await res.json();
    return {
      symbol: j.resolved ?? j.symbol ?? symbol,
      tickSize: Number(j.tick_size ?? j.tickSize ?? 0.01),
      stepSize: Number(j.step_size ?? j.stepSize ?? j.volume_step ?? 0.001),
      minQty: Number(j.volume_min ?? j.minQty ?? 0.001),
      maxQty: Number(j.volume_max ?? j.maxQty ?? 1000),
      pipSize: Number(j.pip_size ?? pipSize),
      volume_min: j.volume_min,
      volume_step: j.volume_step,
      volume_max: j.volume_max,
    };
  } catch {
    return null;
  }
}

export async function fetchBinanceTick(apiBaseUrl: string, symbol = 'XAUUSDT'): Promise<BinanceTick | null> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/tick/${encodeURIComponent(symbol)}`, {
      headers: bridgeHeaders(),
    });
    if (!res.ok) return null;
    return (await res.json()) as BinanceTick;
  } catch {
    return null;
  }
}

export async function fetchBinanceBarsM30(
  apiBaseUrl: string,
  symbol = 'BTCUSDT',
  count = 320,
): Promise<BinanceBar[]> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/bars/${encodeURIComponent(symbol)}?count=${count}`, {
      headers: bridgeHeaders(),
    });
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.bars) ? j.bars : [];
  } catch {
    return [];
  }
}

export async function fetchBinanceAccount(
  apiBaseUrl: string,
): Promise<{ balance: number; equity: number } | null> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/status`, { headers: bridgeHeaders() });
    if (!res.ok) return null;
    const j = await res.json();
    const a = j.account;
    if (!a) return null;
    return {
      balance: Number(a.balance) || 0,
      equity: Number(a.equity) || Number(a.balance) || 0,
    };
  } catch {
    return null;
  }
}

/** Market order via Binance bridge (`POST /api/order`). */
export async function postBinanceOrderFromIntent(
  intent: BrokerOrderIntent,
  opts: {
    baseUrl: string;
    quantity?: number;
    volume?: number;
    symbol?: string;
    spec?: BinanceSymbolSpec | null;
    riskUsd?: number;
  },
): Promise<BinanceOrderResult> {
  const b = base(opts.baseUrl);
  const side = intent.side;
  if (side !== 'BUY' && side !== 'SELL') {
    return { ok: false, status: 0, bodySnippet: 'No BUY/SELL side' };
  }

  const connected = await fetchBinanceConnected(b);
  if (!connected) {
    return {
      ok: false,
      status: 0,
      bodySnippet: 'Binance API not connected — configure API keys in Profile',
      connected: false,
    };
  }

  const sym = opts.symbol ?? intent.symbol ?? 'XAUUSDT';
  let qty = opts.quantity ?? opts.volume ?? 0;

  if (qty <= 0 && opts.riskUsd && intent.entry != null && intent.sl != null) {
    const spec = opts.spec ?? (await fetchBinanceSymbolSpec(b, sym));
    if (spec) {
      qty = quantityFromRiskUsd(opts.riskUsd, intent.entry, intent.sl, spec);
    }
  }
  if (qty <= 0 && opts.volume) {
    const spec = opts.spec ?? (await fetchBinanceSymbolSpec(b, sym));
    qty = spec ? lotsToQuantity(opts.volume, spec) : opts.volume;
  }
  if (qty <= 0) qty = 0.001;

  const spec = opts.spec ?? (await fetchBinanceSymbolSpec(b, sym));
  const exchangeTick = spec?.tickSize ?? 0.01;
  const entryPx = intent.entry ?? 0;
  const normalized = normalizeOrderPrices(entryPx, intent.sl ?? null, intent.tp1 ?? null, exchangeTick);

  const body = {
    symbol: sym,
    side,
    volume: qty,
    sl: normalized.sl,
    tp: normalized.tp,
  };

  try {
    const res = await fetch(`${b}/api/order`, {
      method: 'POST',
      headers: bridgeHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
    let j: Record<string, unknown> = {};
    try {
      j = JSON.parse(text) as Record<string, unknown>;
    } catch {
      /* keep text */
    }
    if (!res.ok) {
      if (typeof j.detail === 'string') snippet = j.detail;
      else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
    }
    const num = (k: string) => {
      const v = j[k];
      return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
    };
    return {
      ok: res.ok && !!j.ok,
      status: res.status,
      bodySnippet: snippet,
      connected: true,
      intendedPrice: num('intended_price'),
      fillPrice: num('fill_price'),
      spreadPips: num('spread_pips'),
      slippagePips: num('slippage_pips'),
      latencyMs: num('latency_ms'),
      orderId: num('order'),
      clientOrderId: typeof j.client_order_id === 'string' ? j.client_order_id : undefined,
      broker: typeof j.broker === 'string' ? j.broker : 'binance',
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, bodySnippet: trimSnippet(msg), connected };
  }
}
