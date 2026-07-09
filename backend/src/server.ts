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
import { handleBinanceProxy, isBinanceProxyPath } from './binanceProxy';
import { attachBinanceWebSocketProxy } from './binanceWsProxy';
import { handleAuthRoute, isAuthPath } from './auth/routes';
import { isStrategyFreezeEnforced, mergeFrozenDeskCfg, verifyFrozenStrategy } from '../strategy/frozenProduction';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = path.join(BACKEND_ROOT, '..');
const DIST_DIR = path.join(REPO_ROOT, 'frontend', 'dist');
const MANIFEST_PATHS = [
  path.join(DIST_DIR, 'release-manifest.json'),
  '/opt/bilshenz/frontend/dist/release-manifest.json',
];

type ReleaseManifest = {
  versionName?: string;
  versionCode?: number;
  gitCommit?: string;
  gitShort?: string;
  buildTime?: string;
  apkFile?: string;
  sha256?: string;
  sizeBytes?: number;
  deskApiUrl?: string;
  binanceApiUrl?: string;
};

function readReleaseManifest(): ReleaseManifest | null {
  for (const mp of MANIFEST_PATHS) {
    try {
      if (!fs.existsSync(mp)) continue;
      return JSON.parse(fs.readFileSync(mp, 'utf8')) as ReleaseManifest;
    } catch {
      /* skip */
    }
  }
  return null;
}

function distApkCandidates(): string[] {
  const manifest = readReleaseManifest();
  const fromManifest = manifest?.apkFile
    ? [path.join(DIST_DIR, manifest.apkFile), path.join('/opt/bilshenz/frontend/dist', manifest.apkFile)]
    : [];
  return [
    ...fromManifest,
    process.env.BILSHENZ_APK_PATH?.trim(),
    path.join(DIST_DIR, 'bilshenz.apk'),
    path.join(DIST_DIR, 'bilshenz-release.apk'),
    path.join(DIST_DIR, 'bilshenz-release-signed.apk'),
    '/opt/bilshenz/frontend/dist/bilshenz.apk',
    '/opt/bilshenz/frontend/dist/bilshenz-release.apk',
  ].filter((p): p is string => !!p);
}

function resolveApkPath(): string | null {
  for (const p of distApkCandidates()) {
    try {
      if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    } catch {
      /* skip */
    }
  }
  return null;
}

function serveApkDownload(res: http.ServerResponse, apkPath: string, downloadName?: string): void {
  const stat = fs.statSync(apkPath);
  const manifest = readReleaseManifest();
  const fname =
    downloadName ||
    manifest?.apkFile ||
    `bilshenz-v${manifest?.versionName ?? 'release'}.apk`;
  res.writeHead(200, {
    'Content-Type': 'application/vnd.android.package-archive',
    'Content-Disposition': `attachment; filename="${fname}"`,
    'Content-Length': stat.size,
    'Cache-Control': 'no-store, no-cache, must-revalidate',
    'Pragma': 'no-cache',
    'X-Bilshenz-Build': manifest?.buildTime ?? '',
    'X-Bilshenz-Commit': manifest?.gitShort ?? manifest?.gitCommit ?? '',
    'X-Bilshenz-Version': manifest?.versionName ?? '',
    'X-Bilshenz-VersionCode': manifest?.versionCode != null ? String(manifest.versionCode) : '',
    'X-Bilshenz-SHA256': manifest?.sha256 ?? '',
  });
  fs.createReadStream(apkPath).pipe(res);
}

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

const MAX_BODY_BYTES = 512 * 1024; // 512 KB max request body

function readJson<T>(req: http.IncomingMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let totalLen = 0;
    req.on('data', (c) => {
      totalLen += c.length;
      if (totalLen > MAX_BODY_BYTES) {
        req.destroy();
        reject(new Error('Request body too large'));
        return;
      }
      chunks.push(c);
    });
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
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bridge-Token');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const urlEarly = new URL(req.url ?? '/', `http://${req.headers.host ?? '127.0.0.1'}`);

  if (urlEarly.pathname === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, service: 'desk-api' }));
    return;
  }

  // Public APK install — uses desk-api port 8791 (already open on VPS firewall).
  if (urlEarly.pathname === '/download/manifest.json' && req.method === 'GET') {
    const manifest = readReleaseManifest();
    const apkPath = resolveApkPath();
    res.writeHead(manifest ? 200 : 404, {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
    });
    res.end(
      JSON.stringify(
        manifest
          ? {
              ok: true,
              ...manifest,
              apkPresent: !!apkPath,
              apkSizeBytes: apkPath ? fs.statSync(apkPath).size : null,
            }
          : { ok: false, error: 'manifest_not_found' },
      ),
    );
    return;
  }

  if (
    (urlEarly.pathname === '/download/bilshenz.apk' ||
      urlEarly.pathname === '/download/bilshenz-release.apk' ||
      urlEarly.pathname.startsWith('/download/bilshenz-v')) &&
    req.method === 'GET'
  ) {
    let apkPath = resolveApkPath();
    if (urlEarly.pathname.startsWith('/download/bilshenz-v')) {
      const versioned = path.basename(urlEarly.pathname);
      const candidates = [
        path.join(DIST_DIR, versioned),
        path.join('/opt/bilshenz/frontend/dist', versioned),
      ];
      for (const c of candidates) {
        if (fs.existsSync(c)) {
          apkPath = c;
          break;
        }
      }
    }
    if (!apkPath) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'apk_not_found',
          detail: 'No fresh APK — run deploy/ubuntu/build-apk-on-vps.sh on the VPS.',
        }),
      );
      return;
    }
    serveApkDownload(res, apkPath, path.basename(apkPath));
    return;
  }

  if (urlEarly.pathname === '/download' && req.method === 'GET') {
    const apkPath = resolveApkPath();
    const manifest = readReleaseManifest();
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(
      JSON.stringify({
        ok: !!apkPath,
        apkUrl: apkPath ? '/download/bilshenz.apk' : null,
        manifestUrl: '/download/manifest.json',
        sizeBytes: apkPath ? fs.statSync(apkPath).size : null,
        versionName: manifest?.versionName ?? null,
        versionCode: manifest?.versionCode ?? null,
        gitCommit: manifest?.gitShort ?? manifest?.gitCommit ?? null,
        buildTime: manifest?.buildTime ?? null,
        sha256: manifest?.sha256 ?? null,
      }),
    );
    return;
  }

  // User auth — public routes (register/login/refresh); /me requires user JWT
  if (isAuthPath(urlEarly.pathname)) {
    if (await handleAuthRoute(req, res, urlEarly)) return;
  }

  // Binance proxy — require desk-api auth when DESK_API_KEY is set (mobile sends Bearer via binanceHeaders).
  if (isBinanceProxyPath(urlEarly.pathname)) {
    if (!authOk(req)) {
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'unauthorized' }));
      return;
    }
    try {
      if (await handleBinanceProxy(req, res, urlEarly)) return;
    } catch {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ detail: 'Binance bridge unreachable. Ensure Bilshenz-Binance-API is running.' }));
      return;
    }
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

// Bind 0.0.0.0 so mobile app can reach VPS; Binance bridge stays on 127.0.0.1 or LAN.
attachBinanceWebSocketProxy(server, (socket) => {
  socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
  socket.destroy();
});

const isProductionDesk =
  process.env.PRODUCTION_MODE === '1' || process.env.NODE_ENV === 'production';

if (isProductionDesk) {
  if (!API_KEY) {
    console.error('[desk-api] FATAL: DESK_API_KEY required when PRODUCTION_MODE=1');
    process.exit(1);
  }
  if (!process.env.AUTH_JWT_SECRET?.trim() || process.env.AUTH_JWT_SECRET.trim().length < 32) {
    console.error('[desk-api] FATAL: AUTH_JWT_SECRET required (min 32 chars) when PRODUCTION_MODE=1');
    process.exit(1);
  }
}

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[desk-api] listening on http://0.0.0.0:${PORT} (LAN/VPS + localhost)`);
  console.log(`[desk-api] POST /v1/desk/compute · POST /v1/desk/execute-gate · /v1/binance/*`);
  console.log(`[desk-api] /v1/auth/* — user registration, login, JWT sessions`);
  console.log(`[desk-api] POST /v1/validation/event · GET /v1/validation/events · GET /v1/validation/freeze-status`);
  if (isStrategyFreezeEnforced()) console.log('[desk-api] STRATEGY_FREEZE=1 — locked production config');
  if (!API_KEY) console.warn('[desk-api] WARNING: DESK_API_KEY not set — desk routes open on LAN');
  if (!process.env.AUTH_JWT_SECRET?.trim()) {
    console.warn('[desk-api] WARNING: AUTH_JWT_SECRET not set — dev-only JWT signing active');
  }
});
