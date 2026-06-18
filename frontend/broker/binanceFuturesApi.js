import { getDeskApiUrl } from '../lib/envConfig';
import { TRADING_SYMBOL } from '../lib/tradingSymbol';
import { getDefaultBinanceBridgeUrl, binanceBridgeUrlCandidates } from '../utils/binanceApiUrl';

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
  } else {
    const { getBridgeToken } = require('../lib/envConfig');
    const bridgeToken = getBridgeToken();
    if (bridgeToken) headers['X-Bridge-Token'] = bridgeToken;
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
  const session = await fetchBinanceSession(apiBaseUrl, timeoutMs);
  return session.ok;
}

function parseApiDetail(j, fallback = 'Request failed') {
  if (typeof j?.detail === 'string') return j.detail;
  if (Array.isArray(j?.detail)) {
    return j.detail.map((d) => d?.msg || d?.message || JSON.stringify(d)).join('; ');
  }
  if (j?.detail && typeof j.detail === 'object') {
    return JSON.stringify(j.detail);
  }
  return fallback;
}

export async function fetchBinanceSession(apiBaseUrl, timeoutMs = 12000, retries = 1) {
  const b = base(apiBaseUrl);
  let last = null;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await binanceFetch(b, '/api/status', {}, timeoutMs);
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        let detail = txt.slice(0, 200) || `HTTP ${res.status}`;
        try {
          const j = JSON.parse(txt);
          detail = parseApiDetail(j, detail);
        } catch {
          /* keep txt */
        }
        if (res.status === 401 && /unauthorized/i.test(detail)) {
          detail = 'Bridge auth failed — set EXPO_PUBLIC_BRIDGE_TOKEN to match BRIDGE_TOKEN on the PC bridge.';
        }
        last = { ok: false, connected: false, account: null, mode: null, error: detail };
        if (i < retries) {
          await new Promise((r) => setTimeout(r, 800 * (i + 1)));
          continue;
        }
        return last;
      }
      const j = await res.json();
      const account = j.account && typeof j.account === 'object' ? j.account : null;
      const connected = !!j.connected && !!account;
      return {
        ok: connected,
        connected: !!j.connected,
        account,
        mode: j.mode ?? null,
        testnet: j.testnet,
        error: connected ? null : j.error ?? (j.connected ? 'No account in status' : 'Bridge not connected'),
      };
    } catch (e) {
      last = {
        ok: false,
        connected: false,
        account: null,
        mode: null,
        error: e instanceof Error ? e.message : String(e),
      };
      if (i < retries) {
        await new Promise((r) => setTimeout(r, 800 * (i + 1)));
        continue;
      }
      return last;
    }
  }
  return last ?? { ok: false, connected: false, account: null, mode: null, error: 'Unknown error' };
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
      let detail = parseApiDetail(j, `HTTP ${res.status}`);
      if (res.status === 401 && /unauthorized/i.test(detail)) {
        detail = 'Bridge auth failed — add EXPO_PUBLIC_BRIDGE_TOKEN in .env.local (must match PC bridge BRIDGE_TOKEN).';
      } else if (res.status === 401 && /invalid|api-key|permission|ip/i.test(detail)) {
        detail = `${detail} — check Testnet vs Mainnet toggle matches where you created the key, and enable Futures + Read permissions.`;
      }
      return { ok: false, detail, status: res.status };
    }
    return { ok: true, account: j.account || null, mode: j.mode ?? null };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchBinanceSymbolSpec(apiBaseUrl, symbol = TRADING_SYMBOL, pipSize = 0.1) {
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

export async function fetchBinanceTick(apiBaseUrl, symbol = TRADING_SYMBOL) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/tick/${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchBinanceDeals(apiBaseUrl, limit = 100) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/logs?limit=${limit}`, {}, 15000);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.deals) ? j.deals : [];
  } catch {
    return [];
  }
}

export async function fetchBinancePositions(apiBaseUrl, symbol) {
  const b = base(apiBaseUrl);
  const qs = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
  try {
    const res = await binanceFetch(b, `/api/positions${qs}`, {}, 12000);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.positions) ? j.positions : [];
  } catch {
    return [];
  }
}

export async function fetchBinanceBarsM30(apiBaseUrl, symbol = TRADING_SYMBOL, count = 320, timeoutMs) {
  const b = base(apiBaseUrl);
  const ms = timeoutMs ?? Math.min(45000, 10000 + Math.max(50, count) * 12);
  try {
    const res = await binanceFetch(b, `/api/bars/${encodeURIComponent(symbol)}?count=${count}`, {}, ms);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.bars) ? j.bars : [];
  } catch {
    return [];
  }
}

/** Pick first bridge URL that responds — prefers one with M30 bars, falls back to health-only. */
export async function pickReachableBinanceBridgeUrl(preferred = '', symbol = TRADING_SYMBOL) {
  let healthOnly = null;
  for (const url of binanceBridgeUrlCandidates(preferred)) {
    try {
      const health = await binanceFetch(url, '/health', {}, 8000);
      if (!health.ok) continue;
      if (!healthOnly) healthOnly = url.replace(/\/$/, '');
      const bars = await fetchBinanceBarsM30(url, symbol, 10, 20000);
      if (bars.length > 0) return url.replace(/\/$/, '');
    } catch {
      /* try next */
    }
  }
  return healthOnly;
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
  const sym = opts.symbol ?? intent.symbol ?? TRADING_SYMBOL;
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

/** Poll order fill status after market order (reconciliation). */
export async function fetchBinanceOrderStatus(apiBaseUrl, orderId, symbol = TRADING_SYMBOL, timeoutMs = 15000) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(
      b,
      `/api/order/${encodeURIComponent(String(orderId))}?symbol=${encodeURIComponent(symbol)}`,
      {},
      timeoutMs,
    );
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, error: typeof j.detail === 'string' ? j.detail : `HTTP ${res.status}` };
    }
    return { ok: true, order: j.order ?? null };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export function getDefaultBinanceApiUrl(port = 8766) {
  const fromEnv = process.env.EXPO_PUBLIC_BINANCE_API_URL?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const desk = getDeskApiUrl();
  if (desk && !/^https?:\/\/(localhost|127\.0\.0\.1)/i.test(desk)) {
    return `${desk.replace(/\/$/, '')}/v1/binance`;
  }
  return getDefaultBinanceBridgeUrl(port);
}
