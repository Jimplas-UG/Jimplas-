import { getDeskApiUrl } from '../lib/envConfig';

function trimSnippet(s, max = 400) {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

function base(baseUrl) {
  return baseUrl.replace(/\/$/, '');
}

export function binanceHeaders(baseUrl, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (baseUrl.includes('/v1/binance')) {
    const { getDeskApiKey } = require('../lib/envConfig');
    const key = getDeskApiKey();
    if (key) headers.Authorization = `Bearer ${key}`;
  }
  return headers;
}

export async function binanceFetch(baseUrl, path, options = {}, timeoutMs = 15000) {
  const b = base(baseUrl);
  const url = path.startsWith('http') ? path : `${b}${path.startsWith('/') ? path : `/${path}`}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: ctrl.signal,
      headers: binanceHeaders(b, options.headers || {}),
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchBinanceConnected(apiBaseUrl, timeoutMs = 12000) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, '/api/status', {}, timeoutMs);
    if (!res.ok) return false;
    const j = await res.json();
    return !!j.connected;
  } catch {
    return false;
  }
}

export async function probeBinanceBridge(apiBaseUrl, attempts = 3) {
  for (let i = 0; i < attempts; i++) {
    if (await fetchBinanceConnected(apiBaseUrl)) return true;
    if (i < attempts - 1) await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
  }
  return false;
}

export async function postBinanceAttach(apiBaseUrl, timeoutMs = 15000) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, '/api/attach', { method: 'POST' }, timeoutMs);
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, detail: typeof j.detail === 'string' ? j.detail : JSON.stringify(j) };
    }
    return { ok: true, account: j.account || null };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

export async function postBinanceLogin(apiBaseUrl, body, timeoutMs = 20000) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(
      b,
      '/api/login',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      timeoutMs,
    );
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, detail: typeof j.detail === 'string' ? j.detail : JSON.stringify(j) };
    }
    return { ok: true, account: j.account || null };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchBinanceSymbolSpec(apiBaseUrl, symbol = 'XAUUSDT', pipSize = 0.1) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/symbol/${encodeURIComponent(symbol)}?pip_size=${pipSize}`);
    if (!res.ok) return null;
    const j = await res.json();
    return {
      symbol: j.resolved ?? j.symbol ?? symbol,
      tickSize: Number(j.tick_size ?? j.tickSize ?? 0.01),
      stepSize: Number(j.step_size ?? j.stepSize ?? j.volume_step ?? 0.001),
      minQty: Number(j.volume_min ?? 0.001),
      maxQty: Number(j.volume_max ?? 1000),
      pipSize: Number(j.pip_size ?? pipSize),
    };
  } catch {
    return null;
  }
}

export async function fetchBinanceTick(apiBaseUrl, symbol = 'XAUUSDT') {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/tick/${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchBinanceBarsM30(apiBaseUrl, symbol = 'XAUUSDT', count = 320) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/bars/${encodeURIComponent(symbol)}?count=${count}`);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.bars) ? j.bars : [];
  } catch {
    return [];
  }
}

export async function postBinanceOrderFromIntent(intent, opts) {
  const b = base(opts.baseUrl);
  const side = intent.side;
  if (side !== 'BUY' && side !== 'SELL') {
    return { ok: false, status: 0, bodySnippet: 'No BUY/SELL side' };
  }
  const connected = await fetchBinanceConnected(b);
  if (!connected) {
    return { ok: false, status: 0, bodySnippet: 'Binance API not connected', connected: false };
  }
  const sym = opts.symbol ?? intent.symbol ?? 'XAUUSDT';
  const body = {
    symbol: sym,
    side,
    volume: opts.quantity ?? opts.volume ?? 0.001,
    sl: intent.sl,
    tp: intent.tp1,
  };
  try {
    const res = await binanceFetch(
      b,
      '/api/order',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      30000,
    );
    const text = await res.text();
    let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
    let j = {};
    try {
      j = JSON.parse(text);
    } catch {
      /* text */
    }
    if (!res.ok) {
      if (typeof j.detail === 'string') snippet = j.detail;
      else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
    }
    const num = (k) => (typeof j[k] === 'number' && Number.isFinite(j[k]) ? j[k] : undefined);
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
      broker: j.broker || 'binance',
    };
  } catch (e) {
    return { ok: false, status: 0, bodySnippet: trimSnippet(e instanceof Error ? e.message : String(e)), connected };
  }
}

export function getDefaultBinanceApiUrl(port = 8766) {
  const fromEnv = process.env.EXPO_PUBLIC_BINANCE_API_URL?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const desk = getDeskApiUrl();
  if (desk && !/^https?:\/\/(localhost|127\.0\.0\.1)/i.test(desk)) {
    return `${desk.replace(/\/$/, '')}/v1/binance`;
  }
  return `http://127.0.0.1:${port}`;
}
