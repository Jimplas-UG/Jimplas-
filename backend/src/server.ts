/**
 * Private desk API — strategy engine runs here only (not in Expo bundle when remote mode on).
 * Start: npm run desk-api
 * Env: DESK_API_PORT=8791, DESK_API_KEY=your-secret
 */
import http from 'node:http';
import { computeBilshenzSnapshot, defaultBilshenzConfig } from '../engine';
import type { BilshenzEngineConfig, EquityRiskContext, MarketBundle } from '../engine/types';
import { canExecuteTrade } from '../broker/tradeExecutionGates';
import { publicBlockReason } from '../security/publicLabels';
import { handleValidationRoute } from './validationRoutes';
import { isStrategyFreezeEnforced, mergeFrozenDeskCfg, verifyFrozenStrategy } from '../strategy/frozenProduction';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

const PORT = Number(process.env.DESK_API_PORT) || 8791;
const API_KEY = process.env.DESK_API_KEY?.trim() || '';

type DeskPrefs = {
  spread?: number;
  geoRisk?: 'LOW' | 'MEDIUM' | 'HIGH';
  newsActive?: boolean;
  nfpBlackout?: boolean;
  maxDailyTrades?: number;
  simUsdPerEnginePip?: number;
};

function mergeCfg(prefs: DeskPrefs): BilshenzEngineConfig {
  if (isStrategyFreezeEnforced()) {
    const frozen = mergeFrozenDeskCfg(prefs.spread);
    const check = verifyFrozenStrategy(BACKEND_ROOT, frozen);
    if (!check.ok) {
      throw new Error(`Strategy freeze: ${check.errors.join('; ')}`);
    }
    return {
      ...frozen,
      simUsdPerEnginePip:
        prefs.simUsdPerEnginePip != null && prefs.simUsdPerEnginePip > 0
          ? prefs.simUsdPerEnginePip
          : frozen.simUsdPerEnginePip,
    };
  }
  const cap = Number.isFinite(prefs.maxDailyTrades)
    ? Math.max(1, Math.min(10, Math.floor(prefs.maxDailyTrades!)))
    : defaultBilshenzConfig.maxDailyTrades;
  const simUsd =
    prefs.simUsdPerEnginePip != null && prefs.simUsdPerEnginePip > 0
      ? prefs.simUsdPerEnginePip
      : defaultBilshenzConfig.simUsdPerEnginePip;
  return {
    ...defaultBilshenzConfig,
    currentSpreadPips: prefs.spread ?? defaultBilshenzConfig.currentSpreadPips,
    geoRisk: prefs.geoRisk ?? 'LOW',
    newsActive: !!prefs.newsActive,
    nfpBlackout: !!prefs.nfpBlackout,
    maxDailyTrades: cap,
    simUsdPerEnginePip: simUsd,
  };
}

function sanitizeForClient(raw: ReturnType<typeof computeBilshenzSnapshot>, geoRisk?: string) {
  const trade = raw.trade;
  const side = trade?.side === 'BUY' ? 'BUY' : trade?.side === 'SELL' ? 'SELL' : 'WAIT';
  const status =
    side === 'WAIT' ? 'WAIT' : trade?.allowed ? 'READY' : 'BLOCKED';
  const riskLevel =
    raw.risk?.geoHigh || geoRisk === 'HIGH'
      ? 'HIGH'
      : raw.risk?.geoMedium || geoRisk === 'MEDIUM'
        ? 'MEDIUM'
        : raw.risk?.chopZone || raw.risk?.yieldHigh
          ? 'MEDIUM'
          : 'LOW';

  return {
    asOf: raw.asOf,
    session: {
      inSession: !!raw.session?.inSession,
      sessionLabel: raw.session?.sessionLabel ?? 'STANDBY',
      preLondon: !!raw.session?.preLondon,
      london: !!raw.session?.london,
      newYork: !!raw.session?.newYork,
    },
    trade: {
      allowed: !!trade?.allowed && status === 'READY',
      side: side === 'WAIT' ? null : side,
      entry: trade?.entry ?? null,
      sl: trade?.sl ?? null,
      tp1: trade?.tp1 ?? null,
      rr: trade?.rr ?? null,
      confidencePct: trade?.confidencePct ?? 0,
      status,
      statusLine:
        status === 'READY'
          ? 'Signal active — execution permitted'
          : status === 'BLOCKED'
            ? 'Signal blocked — stand by'
            : 'Scanning market — no active signal',
    },
    winRate: {
      totalWins: raw.winRate?.totalWins ?? 0,
      totalLosses: raw.winRate?.totalLosses ?? 0,
      winRatePct: raw.winRate?.winRatePct ?? 0,
    },
    risk: { riskLevel, atrMode: raw.risk?.atrMode?.split('—')[0]?.trim() ?? '—' },
    signals: {
      anyBuy: !!raw.signals?.anyBuy,
      anySell: !!raw.signals?.anySell,
      p1Buy: !!raw.signals?.p1Buy,
      p1Sell: !!raw.signals?.p1Sell,
      p2Buy: !!raw.signals?.p2Buy,
      p2Sell: !!raw.signals?.p2Sell,
      p3Buy: !!raw.signals?.p3Buy,
      p3Sell: !!raw.signals?.p3Sell,
    },
    _internal: {
      gates: raw.gates,
      blocks: trade?.blocks ?? [],
    },
  };
}

function authOk(req: http.IncomingMessage): boolean {
  if (!API_KEY) return true;
  const h = req.headers.authorization ?? '';
  return h === `Bearer ${API_KEY}`;
}

function readJson<T>(req: http.IncomingMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, service: 'desk-api' }));
    return;
  }

  if (!authOk(req)) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'unauthorized' }));
    return;
  }

  try {
    const url = new URL(req.url ?? '/', `http://${req.headers.host ?? '127.0.0.1'}`);
    if (handleValidationRoute(req, res, url)) return;

    if (req.url === '/v1/desk/compute' && req.method === 'POST') {
      const body = await readJson<{
        bundle: MarketBundle;
        prefs?: DeskPrefs;
        journalRows?: unknown[];
        dailyTradeCount?: number;
        nowUtcMs?: number;
        equityRisk?: EquityRiskContext;
      }>(req);
      const cfg = mergeCfg(body.prefs ?? {});
      const raw = computeBilshenzSnapshot({
        bundle: body.bundle,
        cfg,
        dailyTradeCount: body.dailyTradeCount ?? 0,
        journalRows: (body.journalRows as never[]) ?? [],
        nowUtcMs: body.nowUtcMs ?? Date.now(),
        equityRisk: body.equityRisk ?? null,
      });
      const out = sanitizeForClient(raw, body.prefs?.geoRisk);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(out));
      return;
    }

    if (req.url === '/v1/desk/execute-gate' && req.method === 'POST') {
      const body = await readJson<{
        bundle: MarketBundle;
        prefs?: DeskPrefs;
        journalRows?: unknown[];
        dailyTradeCount?: number;
        nowUtcMs?: number;
        equityRisk?: EquityRiskContext;
      }>(req);
      const cfg = mergeCfg(body.prefs ?? {});
      const raw = computeBilshenzSnapshot({
        bundle: body.bundle,
        cfg,
        dailyTradeCount: body.dailyTradeCount ?? 0,
        journalRows: (body.journalRows as never[]) ?? [],
        nowUtcMs: body.nowUtcMs ?? Date.now(),
        equityRisk: body.equityRisk ?? null,
      });
      const gate = canExecuteTrade(raw, raw.trade);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          ok: gate.ok,
          reason: gate.ok ? undefined : publicBlockReason(gate.reason),
        })
      );
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'not_found' }));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: msg }));
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[desk-api] listening on http://127.0.0.1:${PORT}`);
  console.log(`[desk-api] POST /v1/desk/compute · POST /v1/desk/execute-gate`);
  console.log(`[desk-api] POST /v1/validation/event · GET /v1/validation/events · GET /v1/validation/freeze-status`);
  if (isStrategyFreezeEnforced()) console.log('[desk-api] STRATEGY_FREEZE=1 — locked production config');
  if (!API_KEY) console.warn('[desk-api] WARNING: DESK_API_KEY not set — open to LAN');
});
