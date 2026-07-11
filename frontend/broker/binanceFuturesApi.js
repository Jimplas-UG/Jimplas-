import { getDeskApiUrl } from '../lib/envConfig';
import { DEFAULT_CHART_SYMBOL, formatPairLabel, normalizeFuturesSymbol } from '../lib/futuresSymbol';
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
          await new Promise((r) => setTimeout(r, 250 * (i + 1)));
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
        can_execute: j.can_execute,
        exec_enabled: j.exec_enabled,
        exec_block: j.exec_block ?? null,
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
        await new Promise((r) => setTimeout(r, 250 * (i + 1)));
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
    return {
      ok: true,
      account: j.account || null,
      mode: j.mode ?? null,
      testnet: j.testnet,
      can_execute: j.can_execute,
      exec_enabled: j.exec_enabled,
      exec_block: j.exec_block ?? null,
    };
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

export async function postBinanceLogin(apiBaseUrl, body, timeoutMs = 45000) {
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
      if (res.status === 401 && /unauthorized/i.test(detail) && !/invalid|api-key|signature|permission/i.test(detail)) {
        detail = 'Bridge auth failed — APK must include DESK_API_KEY matching the VPS.';
      } else if (res.status === 401 && /invalid|api-key|permission|ip/i.test(detail)) {
        detail = `${detail} — check Testnet vs Mainnet toggle matches where you created the key, and enable Futures + Read permissions.`;
      }
      return { ok: false, detail, status: res.status };
    }
    return {
      ok: true,
      account: j.account || null,
      mode: j.mode ?? null,
      testnet: j.testnet,
      auto_detected: !!j.auto_detected,
      can_execute: j.can_execute,
      exec_enabled: j.exec_enabled,
      exec_block: j.exec_block ?? null,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/abort/i.test(msg)) {
      return {
        ok: false,
        detail: 'Aborted — login took too long (VPS↔Binance). Tap Retry Connect.',
      };
    }
    return { ok: false, detail: msg };
  }
}

export async function fetchBinanceSymbols(apiBaseUrl, { refresh = false } = {}) {
  const b = base(apiBaseUrl);
  try {
    const qs = refresh ? '?refresh=1' : '';
    const res = await binanceFetch(b, `/api/symbols${qs}`, {}, 30000);
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.symbols) ? j.symbols : [];
  } catch {
    return [];
  }
}

export async function validateFuturesSymbol(apiBaseUrl, symbol) {
  const sym = normalizeFuturesSymbol(symbol);
  if (!sym) return { valid: false, symbol: sym, reason: 'empty' };
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/symbols/${encodeURIComponent(sym)}/validate`, {}, 15000);
    if (!res.ok) return { valid: false, symbol: sym, reason: `http_${res.status}` };
    return await res.json();
  } catch {
    return { valid: false, symbol: sym, reason: 'network' };
  }
}

export async function fetchBinanceSymbolSpec(apiBaseUrl, symbol = DEFAULT_CHART_SYMBOL, pipSize = 0.1) {
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

export async function fetchBinanceTick(apiBaseUrl, symbol = DEFAULT_CHART_SYMBOL) {
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

export async function fetchBinanceBarsM30(
  apiBaseUrl,
  symbol = DEFAULT_CHART_SYMBOL,
  count = 320,
  timeoutMs,
  { retries = 3 } = {},
) {
  const b = base(apiBaseUrl);
  const ms = timeoutMs ?? Math.min(45000, 10000 + Math.max(50, count) * 12);
  let lastErr = 'Bars request failed';
  let lastStatus = 0;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await binanceFetch(b, `/api/bars/${encodeURIComponent(symbol)}?count=${count}`, {}, ms);
      const text = await res.text().catch(() => '');
      if (!res.ok) {
        lastStatus = res.status;
        try {
          const j = JSON.parse(text);
          lastErr = parseApiDetail(j, text.slice(0, 200) || `HTTP ${res.status}`);
        } catch {
          lastErr = text.slice(0, 200) || `HTTP ${res.status}`;
        }
        if (res.status === 401 && /unauthorized/i.test(lastErr)) {
          lastErr =
            b.includes('/v1/binance')
              ? 'Desk auth failed — set EXPO_PUBLIC_DESK_API_KEY to match DESK_API_KEY on desk-api.'
              : 'Bridge auth failed — set EXPO_PUBLIC_BRIDGE_TOKEN to match BRIDGE_TOKEN on the PC bridge.';
        }
        if (attempt < retries && (res.status >= 500 || res.status === 429)) {
          await new Promise((r) => setTimeout(r, 900 * (attempt + 1)));
          continue;
        }
        return { ok: false, bars: [], error: lastErr, status: lastStatus };
      }
      let j = {};
      try {
        j = JSON.parse(text);
      } catch {
        return { ok: false, bars: [], error: 'Invalid bars JSON from bridge', status: res.status };
      }
      const bars = Array.isArray(j.bars) ? j.bars : [];
      if (!bars.length) {
        lastErr = 'Bridge returned empty bars array';
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 900 * (attempt + 1)));
          continue;
        }
        return { ok: false, bars: [], error: lastErr, status: res.status };
      }
      return { ok: true, bars, error: null, status: res.status };
    } catch (e) {
      lastErr = e instanceof Error ? e.message : String(e);
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 900 * (attempt + 1)));
        continue;
      }
      return { ok: false, bars: [], error: lastErr, status: lastStatus };
    }
  }
  return { ok: false, bars: [], error: lastErr, status: lastStatus };
}

/** Last known-good bridge URL — instant reconnect on credential re-entry. */
let cachedBridgeUrl = null;

export async function probeBridgeHealth(url, timeoutMs = 700) {
  const u = String(url || '').trim().replace(/\/$/, '');
  if (!u) return null;
  const health = await binanceFetch(u, '/health', {}, timeoutMs);
  return health.ok ? u : null;
}

/** First URL from list that responds — resolves on first success. */
function firstReachableBridge(urls, timeoutMs) {
  const list = [...new Set(urls.map((u) => String(u || '').trim().replace(/\/$/, '')).filter(Boolean))];
  if (!list.length) return Promise.resolve(null);
  return new Promise((resolve) => {
    let settled = false;
    let failures = 0;
    const done = (v) => {
      if (settled) return;
      settled = true;
      resolve(v);
    };
    for (const url of list) {
      probeBridgeHealth(url, timeoutMs)
        .then((ok) => {
          if (ok) {
            cachedBridgeUrl = ok;
            done(ok);
          } else {
            failures += 1;
            if (failures >= list.length) done(null);
          }
        })
        .catch(() => {
          failures += 1;
          if (failures >= list.length) done(null);
        });
    }
  });
}

/** Pick first bridge URL that responds to /health — cached + preferred URL first. */
export async function pickReachableBinanceBridgeUrl(preferred = '', _symbol = DEFAULT_CHART_SYMBOL) {
  const pref = String(preferred || '').trim().replace(/\/$/, '');

  if (cachedBridgeUrl) {
    const hit = await probeBridgeHealth(cachedBridgeUrl, 450);
    if (hit) return hit;
    cachedBridgeUrl = null;
  }

  if (pref) {
    const hit = await probeBridgeHealth(pref, 700);
    if (hit) {
      cachedBridgeUrl = hit;
      return hit;
    }
  }

  const rest = binanceBridgeUrlCandidates(preferred).filter((u) => u !== pref && u !== cachedBridgeUrl);
  const found = await firstReachableBridge(rest, 1100);
  if (found) return found;
  return null;
}

export function rememberBridgeUrl(url) {
  const u = String(url || '').trim().replace(/\/$/, '');
  if (u) cachedBridgeUrl = u;
}

export async function fetchBinanceDiagnostics(apiBaseUrl, timeoutMs = 12000) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, '/api/diagnostics', {}, timeoutMs);
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return await res.json();
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchBinanceTradeCalendar(apiBaseUrl, days = 400) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(b, `/api/trade-calendar?days=${days}`, {}, 15000);
    if (!res.ok) return { ok: false, days: [], total_pnl: 0 };
    return await res.json();
  } catch {
    return { ok: false, days: [], total_pnl: 0 };
  }
}

export async function postBinanceClosePosition(
  apiBaseUrl,
  { symbol = DEFAULT_CHART_SYMBOL, positionSide = null, closePair = false, volume = null } = {},
) {
  const b = base(apiBaseUrl);
  const body = { symbol };
  if (positionSide) body.position_side = String(positionSide).toUpperCase();
  if (closePair) body.close_pair = true;
  if (volume != null) body.volume = volume;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await binanceFetch(
        b,
        '/api/close',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
        30000,
      );
      const text = await res.text();
      let j = {};
      try {
        j = JSON.parse(text);
      } catch {
        /* text */
      }
      let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
      if (!res.ok) {
        if (res.status === 429 && attempt < 2) {
          await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
          continue;
        }
        if (typeof j.detail === 'string') snippet = j.detail;
        else if (j.detail?.error) snippet = String(j.detail.error);
        else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
        else if (j.error) snippet = String(j.error);
      }
      return {
        ok: res.ok && (j.ok === true || (res.ok && Array.isArray(j.closed))),
        status: res.status,
        bodySnippet: snippet,
        connected: true,
        closed: Array.isArray(j.closed) ? j.closed : j.detail?.closed || [],
        latencyMs: j.latency_ms ?? j.detail?.latency_ms,
        error: j.error ?? j.detail?.error,
      };
    } catch (e) {
      if (attempt < 2) {
        await new Promise((r) => setTimeout(r, 600));
        continue;
      }
      return { ok: false, status: 0, bodySnippet: trimSnippet(e instanceof Error ? e.message : String(e)), connected: false };
    }
  }
  return { ok: false, status: 0, bodySnippet: 'Close failed after retries', connected: false };
}

export async function postBinanceCloseAllPositions(apiBaseUrl) {
  const b = base(apiBaseUrl);
  try {
    const res = await binanceFetch(
      b,
      '/api/close-all',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
      120000,
    );
    const text = await res.text();
    let j = {};
    try {
      j = JSON.parse(text);
    } catch {
      /* text */
    }
    let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
    if (!res.ok) {
      if (typeof j.detail === 'string') snippet = j.detail;
      else if (j.detail?.error) snippet = String(j.detail.error);
      else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
      else if (j.error) snippet = String(j.error);
    }
    return {
      ok: res.ok && j.ok !== false,
      status: res.status,
      bodySnippet: snippet,
      connected: true,
      closed: Array.isArray(j.closed) ? j.closed : j.detail?.closed || [],
      symbols: j.symbols || j.detail?.symbols || [],
      latencyMs: j.latency_ms ?? j.detail?.latency_ms,
      error: j.error ?? j.detail?.error,
    };
  } catch (e) {
    return { ok: false, status: 0, bodySnippet: trimSnippet(e instanceof Error ? e.message : String(e)), connected };
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
  const sym = opts.symbol ?? intent.symbol ?? DEFAULT_CHART_SYMBOL;
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
export async function postBinanceMarginMode(apiBaseUrl, { symbol = DEFAULT_CHART_SYMBOL, marginType = 'ISOLATED' } = {}) {
  const b = base(apiBaseUrl);
  const connected = await fetchBinanceConnected(b);
  if (!connected) {
    return { ok: false, status: 0, bodySnippet: 'Binance API not connected', connected: false };
  }
  const mt = String(marginType).toUpperCase() === 'CROSS' ? 'CROSS' : 'ISOLATED';
  try {
    const res = await binanceFetch(
      b,
      '/api/margin',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, margin_type: mt }),
      },
      20000,
    );
    const text = await res.text();
    let j = {};
    try {
      j = JSON.parse(text);
    } catch {
      /* text */
    }
    let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
    if (!res.ok) {
      if (typeof j.detail === 'string') snippet = j.detail;
      else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
    }
    return {
      ok: res.ok && !!j.ok,
      status: res.status,
      bodySnippet: snippet,
      connected: true,
      margin_type: j.margin_type ?? mt,
    };
  } catch (e) {
    return { ok: false, status: 0, bodySnippet: trimSnippet(e instanceof Error ? e.message : String(e)), connected };
  }
}

export async function fetchBinanceOrderStatus(apiBaseUrl, orderId, symbol = DEFAULT_CHART_SYMBOL, timeoutMs = 15000) {
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
