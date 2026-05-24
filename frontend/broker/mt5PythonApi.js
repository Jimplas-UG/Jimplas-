function trimSnippet(s, max = 400) {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

function base(baseUrl) {
  return baseUrl.replace(/\/$/, '');
}

export function mt5Headers(baseUrl, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (baseUrl.includes('/v1/mt5')) {
    const { getDeskApiKey } = require('../lib/envConfig');
    const key = getDeskApiKey();
    if (key) headers.Authorization = `Bearer ${key}`;
  }
  return headers;
}

function vpsTimeoutMs(baseUrl, fallbackMs) {
  return baseUrl.includes('/v1/mt5') ? Math.max(fallbackMs, 18000) : fallbackMs;
}

/** Authenticated MT5 fetch with VPS-aware timeouts. */
export async function mt5Fetch(baseUrl, path, options = {}, timeoutMs = 15000) {
  const b = base(baseUrl);
  const url = path.startsWith('http') ? path : `${b}${path.startsWith('/') ? path : `/${path}`}`;
  const ms = vpsTimeoutMs(b, timeoutMs);
  return fetchWithTimeout(url, { ...options, headers: mt5Headers(b, options.headers || {}) }, ms);
}

export function parseApiErrorBody(text, status) {
  const raw = String(text || '').trim();
  if (raw.startsWith('<') || raw.includes('<!DOCTYPE')) {
    if (/squid|ERR_CONNECT|Connection timed out|could not be retrieved/i.test(raw)) {
      return 'VPS unreachable from your network (proxy timeout). Use Wi‑Fi or try again — desk-api port 8791 is used automatically.';
    }
    return `Server returned HTML instead of JSON (HTTP ${status}). Check API URL and VPS is online.`;
  }
  try {
    const j = JSON.parse(raw);
    if (typeof j.detail === 'string') return j.detail;
    if (j.error) return String(j.error);
  } catch {
    /* plain text */
  }
  return raw.slice(0, 280) || `HTTP ${status}`;
}

/** Fetch with timeout so CONNECT does not spin forever on slow MT5 IPC. */
export async function fetchWithTimeout(url, options = {}, timeoutMs = 45000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } catch (e) {
    if (e?.name === 'AbortError') {
      throw new Error('Request timed out — open MT5 and log in manually, then USE TERMINAL SESSION');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function normServer(s) {
  return String(s || '')
    .trim()
    .toLowerCase();
}

export async function fetchMt5Health(apiBaseUrl, timeoutMs = 8000) {
  const b = base(apiBaseUrl);
  try {
    const res = await fetchWithTimeout(`${b}/health`, { headers: mt5Headers(b) }, vpsTimeoutMs(b, timeoutMs));
    if (!res.ok) return false;
    const j = await res.json().catch(() => ({}));
    return j.ok === true || j.status === 'ok';
  } catch {
    return false;
  }
}

export async function fetchMt5Connected(apiBaseUrl, timeoutMs = 12000) {
  const b = base(apiBaseUrl);
  const ms = vpsTimeoutMs(b, timeoutMs);
  try {
    if (!(await fetchMt5Health(b, Math.min(ms, 10000)))) return false;
    const res = await fetchWithTimeout(`${b}/api/status`, { headers: mt5Headers(b) }, ms);
    if (!res.ok) return false;
    const j = await res.json();
    return !!j.connected;
  } catch {
    return false;
  }
}

/** Retry bridge probe on cold VPS / hung MT5 IPC. */
export async function probeMt5Bridge(apiBaseUrl, attempts = 3) {
  for (let i = 0; i < attempts; i++) {
    if (await fetchMt5Connected(apiBaseUrl)) return true;
    if (i < attempts - 1) {
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    }
  }
  return false;
}

export async function fetchMt5ResolvedSymbol(apiBaseUrl, symbol = 'XAUUSD') {
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

export async function fetchMt5Tick(apiBaseUrl, symbol = 'XAUUSD') {
  const b = base(apiBaseUrl);
  try {
    const res = await fetch(`${b}/api/tick/${encodeURIComponent(symbol)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchMt5BarsM30(apiBaseUrl, symbol = 'XAUUSD', count = 320) {
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

export async function postMt5Attach(apiBaseUrl, timeoutMs = 12000) {
  const b = base(apiBaseUrl);
  try {
    const res = await fetchWithTimeout(
      `${b}/api/attach`,
      { method: 'POST', headers: mt5Headers(b) },
      timeoutMs,
    );
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j);
      return { ok: false, detail, account: null };
    }
    return { ok: true, account: j.account || null };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, detail: msg, account: null };
  }
}

export async function postMt5Login(apiBaseUrl, body, timeoutMs = 45000) {
  const b = base(apiBaseUrl);
  try {
    const res = await fetchWithTimeout(
      `${b}/api/login`,
      {
        method: 'POST',
        headers: mt5Headers(b, { 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      },
      timeoutMs,
    );
    const j = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j);
      return { ok: false, detail, account: null };
    }
    return { ok: true, account: j.account || null };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, detail: msg, account: null };
  }
}

/** If MT5 terminal already has this login+server, skip slow IPC login. */
export async function tryExistingMt5Session(apiBaseUrl, login, server) {
  const b = base(apiBaseUrl);
  const loginNum = parseInt(String(login).trim(), 10);
  if (!Number.isFinite(loginNum) || loginNum <= 0) return { ok: false };
  try {
    const res = await fetchWithTimeout(`${b}/api/status`, { headers: mt5Headers(b) }, 8000);
    if (!res.ok) return { ok: false };
    const j = await res.json();
    const acc = j.account;
    if (!j.connected || !acc) return { ok: false };
    if (Number(acc.login) === loginNum && normServer(acc.server) === normServer(server)) {
      return { ok: true, account: acc };
    }
    return { ok: false };
  } catch {
    return { ok: false };
  }
}

export async function postMt5OrderFromIntent(intent, opts) {
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
    const res = await fetchWithTimeout(
      `${b}/api/order`,
      {
        method: 'POST',
        headers: mt5Headers(b, { 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      },
      vpsTimeoutMs(b, 30000),
    );
    const text = await res.text();
    let snippet = trimSnippet(text || (res.ok ? 'OK' : 'Empty body'));
    if (!res.ok) {
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') snippet = j.detail;
        else if (j.detail) snippet = trimSnippet(JSON.stringify(j.detail));
      } catch {
        /* keep text */
      }
    }
    let j = {};
    try {
      j = JSON.parse(text);
    } catch {
      /* text */
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
      retcode: num('retcode'),
      orderId: num('order'),
      dealId: num('deal'),
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, bodySnippet: trimSnippet(msg), connected };
  }
}
