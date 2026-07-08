/**
 * Mock API responses for offline dev preview — desk and Binance bridges.
 */
import { buildSyntheticMarketBundle } from '../lib/syntheticMarket';
import { ensureDeskSnapshot } from '../lib/snapshotDefaults';

let _apiLog = [];
const MAX_LOG = 40;

export function getMockApiLog() {
  return [..._apiLog];
}

export function clearMockApiLog() {
  _apiLog = [];
}

function logMock(path, detail) {
  _apiLog.unshift({ ts: Date.now(), path, detail });
  if (_apiLog.length > MAX_LOG) _apiLog.length = MAX_LOG;
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => 'application/json' },
  };
}

export function mockDeskCompute(body = {}) {
  logMock('/v1/desk/compute', 'snapshot');
  const bundle = body.bundle ?? buildSyntheticMarketBundle({ count: 320, anchorClose: 2654.2 });
  const last = bundle.m30?.[bundle.m30.length - 1];
  const entry = last?.c ?? 2654.2;
  const sl = entry - 18;
  const tp1 = entry + 24;
  return ensureDeskSnapshot({
    asOf: Date.now(),
    session: {
      inSession: true,
      sessionLabel: 'NEW YORK',
      preLondon: false,
      london: false,
      newYork: true,
    },
    signals: {
      anyBuy: true,
      anySell: false,
      p1Buy: true,
      p1Sell: false,
      p2Buy: false,
      p2Sell: false,
      p3Buy: false,
      p3Sell: false,
    },
    trade: {
      allowed: true,
      side: 'BUY',
      setup: 'P1',
      entry,
      sl,
      tp1,
      rr: 1.33,
      confidencePct: 72,
      status: 'READY',
      statusLine: 'Signal active — mock dev preview',
      setupPill: 'P1',
    },
    winRate: {
      totalWins: 14,
      totalLosses: 6,
      winRatePct: 70,
      p1Wr: 68,
      p2Wr: 72,
      p3Wr: 65,
    },
    risk: { riskLevel: 'LOW', atrMode: 'STANDARD', atrPips: 42 },
    bias: {
      isBullish: true,
      isBearish: false,
      bullStructure: true,
      bearStructure: false,
    },
    sr: {
      nearestRes: entry + 32,
      nearestSup: entry - 28,
      bullClean: true,
      bearClean: false,
    },
    gates: {
      sessionGate: true,
      structureOk: true,
      masterBlock: false,
      maxTradesReached: false,
    },
    _internal: {
      gates: { sessionGate: true, structureOk: true },
      blocks: [],
    },
  });
}

export function mockExecuteGate() {
  logMock('/v1/desk/execute-gate', 'ok');
  return { ok: true, reason: 'MOCK_DEV' };
}

export function mockBinanceStatus() {
  return {
    connected: true,
    mode: 'paper',
    account: {
      balance: 50000,
      equity: 50240,
      currency: 'USDT',
      server: 'mock-paper',
      trade_allowed: true,
      leverage: 10,
      margin_type: mockMarginType,
    },
  };
}


export function mockBars(symbol = 'BTCUSDT', count = 320) {
  const bars = buildSyntheticMarketBundle({ count, anchorClose: symbol.includes('DXY') ? 99.4 : 2654.2 }).m30;
  return { symbol, timeframe: 'M30', bars };
}

export function mockTick(symbol = 'BTCUSDT') {
  const mid = 2654.2;
  return { symbol, bid: mid - 0.15, ask: mid + 0.15, time: Date.now() };
}

let mockHasOpenPosition = true;
let mockMarginType = 'ISOLATED';

export function mockPositions() {
  if (!mockHasOpenPosition) return { positions: [] };
  return {
    positions: [
      {
        ticket: 1001,
        symbol: 'BTCUSDT',
        type: 'BUY',
        volume: 0.05,
        price_open: 2648.5,
        sl: 2630,
        tp: 2678,
        profit: 285.5,
        magic: 77002002,
      },
    ],
  };
}

export function mockOrderOk(side = 'BUY') {
  logMock('/api/order', side);
  return {
    ok: true,
    side,
    fill_price: 2654.35,
    intended_price: 2654.2,
    spread_pips: 1.5,
    slippage_pips: 0.3,
    latency_ms: 42,
    order: 900001,
    broker: 'mock',
  };
}

/**
 * Intercept fetch for bridge/desk URLs when mock mode is on.
 * @returns {Response-like|null} null = pass through to real fetch
 */
export function tryMockFetch(url, init = {}) {
  const u = String(url);
  const method = (init.method || 'GET').toUpperCase();

  if (u.includes('/v1/desk/compute') && method === 'POST') {
    let body = {};
    try {
      body = JSON.parse(init.body || '{}');
    } catch {
      /* ignore */
    }
    return jsonResponse(mockDeskCompute(body));
  }
  if (u.includes('/v1/desk/execute-gate') && method === 'POST') {
    return jsonResponse(mockExecuteGate());
  }
  if (u.includes('/health') || u.endsWith('/ping')) {
    return jsonResponse({ ok: true, service: 'mock-dev-bridge', mode: 'paper' });
  }
  if (u.includes('/api/status')) {
    return jsonResponse(mockBinanceStatus());
  }
  if (u.includes('/api/bars/')) {
    const sym = decodeURIComponent(u.split('/api/bars/')[1]?.split('?')[0] || 'BTCUSDT');
    const count = parseInt(new URL(u, 'http://x').searchParams.get('count') || '320', 10);
    return jsonResponse(mockBars(sym, count));
  }
  if (u.includes('/api/tick/')) {
    const sym = decodeURIComponent(u.split('/api/tick/')[1]?.split('?')[0] || 'BTCUSDT');
    return jsonResponse(mockTick(sym));
  }
  if (u.includes('/api/positions')) {
    return jsonResponse(mockPositions());
  }
  if (u.includes('/api/close') && method === 'POST') {
    mockHasOpenPosition = false;
    logMock('/api/close', 'closed');
    return jsonResponse({
      ok: true,
      closed: [{ symbol: 'BTCUSDT', side: 'BUY', volume: 0.05, fill_price: 2654.35, profit: 285.5 }],
      broker: 'mock',
    });
  }
  if (u.includes('/api/margin') && method === 'POST') {
    try {
      const body = JSON.parse(init.body || '{}');
      mockMarginType = String(body.margin_type || 'ISOLATED').toUpperCase() === 'CROSS' ? 'CROSS' : 'ISOLATED';
    } catch {
      mockMarginType = 'ISOLATED';
    }
    logMock('/api/margin', mockMarginType);
    return jsonResponse({ ok: true, margin_type: mockMarginType, symbol: 'BTCUSDT' });
  }
  if (u.includes('/api/order') && method === 'POST') {
    let side = 'BUY';
    try {
      side = JSON.parse(init.body || '{}').side || side;
    } catch {
      /* ignore */
    }
    return jsonResponse(mockOrderOk(side));
  }
  if (u.includes('/api/attach') || u.includes('/api/login')) {
    return jsonResponse({ ok: true, account: mockBinanceStatus().account, mode: 'mock' });
  }
  if (u.includes('/api/logout')) {
    return jsonResponse({ ok: true });
  }

  return null;
}
