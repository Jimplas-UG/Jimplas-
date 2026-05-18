function trimSnippet(s, max = 400) {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

function base(baseUrl) {
  return baseUrl.replace(/\/$/, '');
}

export async function fetchMt5Connected(apiBaseUrl) {
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

export async function postMt5Login(apiBaseUrl, body) {
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
    const res = await fetch(`${b}/api/order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
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
    return { ok: res.ok, status: res.status, bodySnippet: snippet, connected: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, bodySnippet: trimSnippet(msg), connected };
  }
}
