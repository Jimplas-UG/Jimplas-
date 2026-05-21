import type { BrokerOrderIntent } from './brokerTypes';

export type Mt5OrderResult = {
  ok: boolean;
  status: number;
  bodySnippet: string;
  connected?: boolean;
  intendedPrice?: number;
  fillPrice?: number;
  spreadPips?: number;
  slippagePips?: number;
  latencyMs?: number;
  retcode?: number;
  orderId?: number;
  dealId?: number;
};

export type Mt5Bar = { t: number; o: number; h: number; l: number; c: number };

export type Mt5Tick = {
  symbol?: string;
  bid: number;
  ask: number;
  last?: number;
  time?: number;
};

function trimSnippet(s: string, max = 400): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

function base(baseUrl: string): string {
  return baseUrl.replace(/\/$/, '');
}

export async function fetchMt5Connected(apiBaseUrl: string): Promise<boolean> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/status`);
    if (!res.ok) return false;
    const j = await res.json();
    return !!j.connected;
  } catch {
    return false;
  }
}

export async function fetchMt5ResolvedSymbol(apiBaseUrl: string, symbol = 'XAUUSD'): Promise<string | null> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/symbol/${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    const j = await res.json();
    return typeof j.resolved === 'string' ? j.resolved : null;
  } catch {
    return null;
  }
}

export async function fetchMt5Tick(apiBaseUrl: string, symbol = 'XAUUSD'): Promise<Mt5Tick | null> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/tick/${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    return (await res.json()) as Mt5Tick;
  } catch {
    return null;
  }
}

export async function fetchMt5BarsM30(apiBaseUrl: string, symbol = 'XAUUSD', count = 320): Promise<Mt5Bar[]> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/bars/${encodeURIComponent(symbol)}?count=${count}`);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.bars) ? j.bars : [];
  } catch {
    return [];
  }
}

export async function postMt5Login(
  apiBaseUrl: string,
  body: { login: number; password: string; server: string }
): Promise<{ ok: boolean; detail?: string }> {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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

/** Market order via Python MT5 bridge (`POST /api/order`). Requires prior `/api/login` in Profile. */
export async function postMt5OrderFromIntent(
  intent: BrokerOrderIntent,
  opts: { baseUrl: string; volume?: number; symbol?: string }
): Promise<Mt5OrderResult> {
  const b = base(opts.baseUrl);
  const side = intent.side;
  if (side !== 'BUY' && side !== 'SELL') {
    return { ok: false, status: 0, bodySnippet: 'No BUY/SELL side' };
  }

  const connected = await fetchMt5Connected(b);
  if (!connected) {
    return { ok: false, status: 0, bodySnippet: 'MT5 API not connected — use CONNECT MT5 in Profile', connected: false };
  }

  const sym = opts.symbol ?? intent.symbol ?? 'XAUUSD';
  const body = {
    symbol: sym,
    side,
    volume: opts.volume ?? 0.01,
    sl: intent.sl,
    tp: intent.tp1,
  };

  try {
    const res = await fetch(`${b}/api/order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
      retcode: num('retcode'),
      orderId: num('order'),
      dealId: num('deal'),
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, bodySnippet: trimSnippet(msg), connected };
  }
}

