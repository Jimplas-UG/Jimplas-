/**
 * Headless 30-day Binance Futures forward test — frozen config, live feed, real orders.
 *
 * Prerequisites: Binance bridge running (npm run binance-api on :8766)
 *
 * Usage:
 *   npm run forward-demo:30d
 *   npm run forward-demo:30d -- --dry-run          # signals only, no orders
 *   npm run forward-demo:30d -- --poll-sec=45
 *
 * Stop: Ctrl+C (session state saved; resume with same command)
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildBrokerOrderIntent } from '../broker/webhookBroker';
import { executeBrokerRoutes } from '../broker/executeBrokerRoutes';
import { canExecuteTrade } from '../broker/tradeExecutionGates';
import { fetchBinanceSymbolSpec } from '../broker/binanceFuturesApi';
import { quantityFromRiskUsd } from '../broker/quantityMath';
import {
  buildBundleFromM30Bars,
  computeBilshenzSnapshot,
  pushJournalRow,
  resolveJournalOnBar,
} from '../engine';
import { m30ToM15Bars } from '../engine/m15Bars';
import type { Bar, TradeJournalRow } from '../engine/types';
import {
  appendSafetyLog,
  dailyLossBreached,
  envDryRunEnabled,
  isDuplicateOrder,
  loadSafetyState,
  markOrderExecuted,
  maxDailyTradesLimit,
  recordApiFailure,
  recordApiSuccess,
  saveSafetyState,
  updateEquityTracking,
  type SafetyState,
} from '../production/safetyControls';
import { mergeFrozenDeskCfg, productionFrozenConfig, verifyFrozenStrategy } from '../strategy/frozenProduction';
import {
  jcmWebhookConfigured,
  publishSystemState,
  publishTradeBlocked,
  publishTradeExecuted,
} from '../jcm/jcmSupervisorPublisher';
import { logEquitySnapshot, logForwardMissed, logForwardSignal } from '../validation/logForwardEvent';
import { forwardDemoLogPath } from '../validation/forwardDemoStore';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_ROOT = path.join(__dirname, '..');
const DATA_DIR = path.join(BACKEND_ROOT, 'validation', 'data');
const SESSION_FILE = path.join(DATA_DIR, 'forward-demo-session.json');
const JOURNAL_FILE = path.join(DATA_DIR, 'forward-demo-journal.json');

const BROKER_MODE = (process.env.BROKER_MODE ?? 'binance').trim().toLowerCase();
const BROKER_LABEL = BROKER_MODE === 'paper' ? 'Binance paper' : 'Binance';
const BINANCE_API = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const BROKER_API = BINANCE_API;
const BRIDGE_TOKEN = (process.env.BRIDGE_TOKEN ?? '').trim();
const MAX_FORWARD_SYMBOLS = Math.max(1, parseInt(process.env.FORWARD_MAX_SYMBOLS ?? '40', 10) || 40);
const M30_MS = 30 * 60 * 1000;
const WARMUP_BARS = 200;
const RISK_PCT = Math.max(0.0001, Math.min(0.05, Number(process.env.RISK_PCT ?? '0.005') || 0.005));
const DAYS = 30;
const POLL_SEC_DEFAULT = Math.max(15, parseInt(process.env.FORWARD_POLL_SEC ?? '45', 10) || 45);

function brokerHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (BRIDGE_TOKEN) h['X-Bridge-Token'] = BRIDGE_TOKEN;
  return h;
}

async function brokerFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = {
    ...(init.headers as Record<string, string> | undefined),
    ...brokerHeaders(),
  };
  return fetch(`${BROKER_API}${path.startsWith('/') ? path : `/${path}`}`, { ...init, headers });
}

type SessionState = {
  startedAt: string;
  endsAt: string;
  startMs: number;
  endMs: number;
  lastClosedBarT: number | null;
  lastClosedBarTBySymbol?: Record<string, number>;
  symbolCursor?: number;
  lastEquitySnapMs: number;
  tradeCountToday: number;
  nyDay: string | null;
  server: string | null;
  dryRun: boolean;
};

let brokerSymbols: string[] = [];
let brokerSymbolsLoadedAt = 0;

async function fetchBrokerSymbols(): Promise<string[]> {
  const now = Date.now();
  if (brokerSymbols.length && now - brokerSymbolsLoadedAt < 3600_000) return brokerSymbols;
  const envList = (process.env.FORWARD_SYMBOLS ?? process.env.BINANCE_SYMBOLS ?? '').trim();
  if (envList && envList !== '*') {
    brokerSymbols = envList.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    brokerSymbolsLoadedAt = now;
    return brokerSymbols;
  }
  const res = await brokerFetch('/api/symbols');
  if (!res.ok) throw new Error(`${BROKER_LABEL} symbols HTTP ${res.status}`);
  const j = (await res.json()) as { symbols?: string[] };
  brokerSymbols = (j.symbols ?? []).slice(0, MAX_FORWARD_SYMBOLS);
  brokerSymbolsLoadedAt = now;
  return brokerSymbols;
}

function nextSymbol(session: SessionState, symbols: string[]): string | null {
  if (!symbols.length) return null;
  const idx = (session.symbolCursor ?? 0) % symbols.length;
  session.symbolCursor = (idx + 1) % symbols.length;
  return symbols[idx] ?? null;
}

function lastBarForSymbol(session: SessionState, symbol: string): number | null {
  return session.lastClosedBarTBySymbol?.[symbol] ?? session.lastClosedBarT ?? null;
}

function setLastBarForSymbol(session: SessionState, symbol: string, barT: number): void {
  if (!session.lastClosedBarTBySymbol) session.lastClosedBarTBySymbol = {};
  session.lastClosedBarTBySymbol[symbol] = barT;
  session.lastClosedBarT = barT;
}

function readArg(name: string, def: string): string {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : def;
}

function cliDryRun(): boolean {
  return process.argv.includes('--dry-run');
}

/** Orders blocked when env, CLI, or failsafe says so (session file cannot override env dry-run). */
function effectiveDryRun(safety: SafetyState): boolean {
  if (safety.failsafe) return true;
  if (envDryRunEnabled()) return true;
  if (cliDryRun()) return true;
  return false;
}

function orderIdempotencyKey(symbol: string, barT: number, side: string, setup: string): string {
  return `${symbol}:${barT}:${side}:${setup}`;
}

async function brokerStatus(symbol: string): Promise<{
  connected: boolean;
  trade_allowed: boolean;
  equity: number;
  server: string | null;
  spreadPips: number;
  usdPerPip: number;
}> {
  const st = await brokerFetch('/api/status');
  if (!st.ok) throw new Error(`${BROKER_LABEL} status HTTP ${st.status}`);
  const j = (await st.json()) as {
    connected?: boolean;
    account?: { equity?: number; server?: string; trade_allowed?: boolean };
    trade_allowed?: boolean;
  };
  let spreadPips = 3.08;
  let usdPerPip = 10;
  try {
    const specRes = await brokerFetch(`/api/symbol/${encodeURIComponent(symbol)}?pip_size=0.1`);
    if (specRes.ok) {
      const spec = (await specRes.json()) as { spread_pips?: number; usd_per_pip_per_lot?: number };
      if (spec.spread_pips) spreadPips = spec.spread_pips;
      if (spec.usd_per_pip_per_lot) usdPerPip = spec.usd_per_pip_per_lot;
    }
  } catch {
    /* optional */
  }
  return {
    connected: !!j.connected,
    trade_allowed: !!(j.trade_allowed ?? j.account?.trade_allowed),
    equity: j.account?.equity ?? 1000,
    server: j.account?.server ?? null,
    spreadPips,
    usdPerPip,
  };
}

async function fetchM30Bars(symbol: string, fromMs: number, toMs: number): Promise<Bar[]> {
  const url = `/api/bars/${encodeURIComponent(symbol)}?from_ms=${fromMs}&to_ms=${toMs}`;
  const res = await brokerFetch(url);
  if (!res.ok) {
    const fallback = `/api/bars/${encodeURIComponent(symbol)}?count=1500`;
    const res2 = await brokerFetch(fallback);
    if (!res2.ok) throw new Error(`${BROKER_LABEL} bars ${res2.status}`);
    const j2 = (await res2.json()) as { bars?: Bar[] };
    return (j2.bars ?? []).filter((b) => Number.isFinite(b.t)).sort((a, b) => a.t - b.t);
  }
  const j = (await res.json()) as { bars?: Bar[] };
  return (j.bars ?? []).filter((b) => Number.isFinite(b.t)).sort((a, b) => a.t - b.t);
}

function nyYmdKey(ms: number): string {
  const d = new Date(ms);
  const ny = new Date(d.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  return `${ny.getFullYear()}-${String(ny.getMonth() + 1).padStart(2, '0')}-${String(ny.getDate()).padStart(2, '0')}`;
}

function loadSession(): SessionState | null {
  if (!fs.existsSync(SESSION_FILE)) return null;
  const raw = fs.readFileSync(SESSION_FILE, 'utf8').replace(/^\uFEFF/, '');
  return JSON.parse(raw) as SessionState;
}

function saveSession(s: SessionState): void {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(SESSION_FILE, JSON.stringify(s, null, 2), 'utf8');
}

function loadJournal(): TradeJournalRow[] {
  if (!fs.existsSync(JOURNAL_FILE)) return [];
  const raw = fs.readFileSync(JOURNAL_FILE, 'utf8').replace(/^\uFEFF/, '');
  const j = JSON.parse(raw) as { rows?: TradeJournalRow[] };
  return j.rows ?? [];
}

const DESK_API = (process.env.DESK_API_URL ?? 'http://127.0.0.1:8791').replace(/\/$/, '');
let jcmStatePolls = 0;

async function deskHealthOk(): Promise<boolean> {
  try {
    const r = await fetch(`${DESK_API}/health`);
    return r.ok;
  } catch {
    return false;
  }
}

async function maybePublishJcmSystemState(
  status: Awaited<ReturnType<typeof brokerStatus>>,
  dryRun: boolean
): Promise<void> {
  if (!jcmWebhookConfigured()) return;
  jcmStatePolls += 1;
  if (jcmStatePolls % 10 !== 1) return;
  await publishSystemState({
    brokerConnected: status.connected,
    deskApiOk: await deskHealthOk(),
    forwardBotOk: true,
    accountEquity: status.equity,
    dryRun,
  });
}

function saveJournal(rows: TradeJournalRow[]): void {
  fs.writeFileSync(JOURNAL_FILE, JSON.stringify({ version: 1, rows }, null, 2), 'utf8');
}

function lotsForRisk(equity: number, slPips: number, usdPerPip: number): number {
  const riskUsd = equity * RISK_PCT;
  const denom = Math.max(slPips, 20) * usdPerPip;
  const lots = riskUsd / denom;
  return Math.max(0.01, Math.min(1, Math.round(lots * 100) / 100));
}

async function binanceQuantityForIntent(
  symbol: string,
  equity: number,
  entry: number | null | undefined,
  sl: number | null | undefined,
  pipSize: number,
): Promise<number> {
  const riskUsd = equity * RISK_PCT;
  const spec = await fetchBinanceSymbolSpec(BINANCE_API, symbol, pipSize);
  if (!spec || entry == null || sl == null) return spec?.minQty ?? 0.001;
  const qty = quantityFromRiskUsd(riskUsd, entry, sl, spec);
  return qty > 0 ? qty : spec.minQty;
}

async function tickOnce(session: SessionState, symbol: string): Promise<void> {
  const now = Date.now();
  if (now >= session.endMs) {
    console.error('[forward-demo] 30-day window complete');
    process.exit(0);
  }

  const safety = loadSafetyState();
  session.dryRun = effectiveDryRun(safety);

  if (safety.failsafe) {
    try {
      const probe = await brokerStatus(symbol);
      if (probe.connected && probe.trade_allowed) {
        safety.failsafe = false;
        safety.failsafeReason = null;
        safety.consecutiveApiFailures = 0;
        saveSafetyState(safety);
        session.dryRun = effectiveDryRun(safety);
        console.error(`[forward-demo] Self-healed from FAILSAFE — ${BROKER_LABEL} is back online`);
      } else {
        console.error(`[forward-demo] FAILSAFE — ${BROKER_LABEL} probe: connected=${probe.connected} trade=${probe.trade_allowed}`);
        saveSession(session);
        return;
      }
    } catch {
      console.error(`[forward-demo] FAILSAFE — no trading: ${safety.failsafeReason ?? 'halted'}`);
      saveSession(session);
      saveSafetyState(safety);
      return;
    }
  }

  let status: Awaited<ReturnType<typeof brokerStatus>>;
  try {
    status = await brokerStatus(symbol);
    if (!status.connected) {
      const reason = recordApiFailure(safety, `${BROKER_LABEL} not connected`);
      saveSafetyState(safety);
      if (reason) {
        appendSafetyLog(reason, { failsafe: true });
        console.error(`[forward-demo] FAILSAFE: ${reason}`);
      } else {
        console.error(`[forward-demo] ${BROKER_LABEL} not connected`);
      }
      return;
    }
    recordApiSuccess(safety);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const reason = recordApiFailure(safety, msg);
    saveSafetyState(safety);
    if (reason) {
      appendSafetyLog(reason, { failsafe: true });
      console.error(`[forward-demo] FAILSAFE: ${reason}`);
    } else {
      console.error(`[forward-demo] ${BROKER_LABEL} API error: ${msg}`);
    }
    return;
  }

  const cfg = mergeFrozenDeskCfg(status.spreadPips);
  cfg.maxDailyTrades = maxDailyTradesLimit(cfg.maxDailyTrades);

  if (now - session.lastEquitySnapMs >= 3600_000) {
    logEquitySnapshot(status.equity, { server: status.server ?? undefined });
    session.lastEquitySnapMs = now;
    saveSession(session);
  }

  const fetchFrom = now - 90 * 86400000;
  let m30All: Bar[];
  try {
    m30All = await fetchM30Bars(symbol, fetchFrom, now + M30_MS);
    recordApiSuccess(safety);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const reason = recordApiFailure(safety, `bars: ${msg}`);
    saveSafetyState(safety);
    if (reason) {
      appendSafetyLog(reason, { failsafe: true });
      console.error(`[forward-demo] FAILSAFE: ${reason}`);
    } else {
      console.error(`[forward-demo] bars fetch failed: ${msg}`);
    }
    return;
  }
  if (m30All.length < WARMUP_BARS + 5) {
    console.error(`[forward-demo] ${symbol} too few bars (${m30All.length})`);
    saveSafetyState(safety);
    return;
  }

  const bundle = buildBundleFromM30Bars(m30All);
  const n = bundle.m30.length;
  const signalIdx = cfg.signalOnClosedBarOnly !== false && n >= 2 ? n - 2 : n - 1;
  const bar = bundle.m30[signalIdx]!;

  const prevBarT = lastBarForSymbol(session, symbol);
  if (prevBarT === bar.t) {
    console.error(`[forward-demo] ${symbol} ${new Date().toISOString().slice(11, 19)} waiting for new M30 bar (last: ${new Date(bar.t).toISOString().slice(11, 16)})`);
    return;
  }

  const ymd = nyYmdKey(bar.t);
  if (session.nyDay !== ymd) {
    session.nyDay = ymd;
    session.tradeCountToday = 0;
  }
  updateEquityTracking(safety, ymd, status.equity);

  let journalRows = loadJournal();
  const m15 = m30ToM15Bars(bundle.m30);
  journalRows = resolveJournalOnBar(journalRows, bar, signalIdx, {
    m30: bundle.m30,
    m15,
    cfg,
  });

  await maybePublishJcmSystemState(status, effectiveDryRun(safety));

  if (dailyLossBreached(safety, status.equity)) {
    logForwardMissed({ reason: 'daily loss limit', barTimeMs: bar.t });
    void publishTradeBlocked({
      symbol,
      blockedBy: ['daily_loss_limit'],
    });
    console.error(`[forward-demo] ${symbol} ${new Date(bar.t).toISOString()} blocked: daily loss limit`);
    setLastBarForSymbol(session, symbol, bar.t);
    saveJournal(journalRows);
    saveSession(session);
    saveSafetyState(safety);
    return;
  }

  const snap = computeBilshenzSnapshot({
    bundle,
    cfg,
    dailyTradeCount: session.tradeCountToday,
    journalRows,
    nowUtcMs: bar.t,
    equityRisk: {
      currentEquity: status.equity,
      peakEquity: safety.peakEquity > 0 ? safety.peakEquity : status.equity,
      dayStartEquity: safety.dayStartEquity > 0 ? safety.dayStartEquity : status.equity,
    },
  });

  const trade = snap.trade;
  const gate = canExecuteTrade(snap, trade);

  setLastBarForSymbol(session, symbol, bar.t);
  saveJournal(journalRows);
  saveSession(session);
  saveSafetyState(safety);

  if (!gate.ok) {
    if (snap.signals?.anyBuy || snap.signals?.anySell) {
      logForwardMissed({ reason: gate.reason, barTimeMs: bar.t });
      void publishTradeBlocked({
        symbol,
        direction: trade?.side === 'BUY' ? 'long' : trade?.side === 'SELL' ? 'short' : null,
        blockedBy: [gate.reason],
      });
    }
    console.error(`[forward-demo] ${symbol} ${new Date(bar.t).toISOString()} blocked: ${gate.reason}`);
    return;
  }

  const intent = buildBrokerOrderIntent(trade!, {
    barTimeMs: bar.t,
    runMode: 'live',
    trigger: 'auto',
    symbol,
  });
  if (!intent) return;

  logForwardSignal({
    side: intent.side,
    entry: intent.entry ?? bar.c,
    sl: intent.sl ?? undefined,
    tp: intent.tp1 ?? undefined,
    setup: intent.setup !== 'NONE' ? intent.setup : null,
    barTimeMs: bar.t,
  });

  if (session.tradeCountToday >= cfg.maxDailyTrades) {
    logForwardMissed({ reason: 'max daily trades', barTimeMs: bar.t });
    return;
  }

  const slPips =
    intent.entry != null && intent.sl != null
      ? Math.abs(intent.entry - intent.sl) / cfg.pipSize
      : 20;
  const volume = await binanceQuantityForIntent(symbol, status.equity, intent.entry, intent.sl, cfg.pipSize);
  const setup =
    intent.setup === 'P1' || intent.setup === 'P2' || intent.setup === 'P3' ? intent.setup : 'NONE';
  const idemKey = orderIdempotencyKey(symbol, bar.t, intent.side, setup);

  if (isDuplicateOrder(safety, bar.t, idemKey)) {
    logForwardMissed({ reason: 'duplicate order guard', barTimeMs: bar.t });
    console.error(`[forward-demo] ${new Date(bar.t).toISOString()} blocked: duplicate order guard`);
    saveSafetyState(safety);
    return;
  }

  if (effectiveDryRun(safety)) {
    const why = safety.failsafe
      ? 'failsafe'
      : envDryRunEnabled()
        ? 'FORWARD_DRY_RUN'
        : 'dry-run';
    console.error(`[forward-demo] ${symbol} DRY (${why}) ${intent.side} ${intent.setup} @ ${intent.entry?.toFixed(2)} vol=${volume} bar=${new Date(bar.t).toISOString()}`)
    session.tradeCountToday += 1;
    session.dryRun = true;
    saveSession(session);
    saveSafetyState(safety);
    return;
  }

  const riskUsd = status.equity * RISK_PCT;
  const r = await executeBrokerRoutes({
    intent,
    useBinance: true,
    binanceBaseUrl: BINANCE_API,
    binanceQuantity: volume,
    riskUsd,
    symbol,
  });

  if (r.anyOk) {
    recordApiSuccess(safety);
    markOrderExecuted(safety, bar.t, idemKey);
    session.tradeCountToday += 1;
    const prev = { rows: journalRows, count: journalRows.length };
    const next = pushJournalRow(
      prev,
      {
        anyBuy: intent.side === 'BUY',
        anySell: intent.side === 'SELL',
        barIndex: signalIdx,
        timeStr: new Date(bar.t).toISOString(),
        close: bar.c,
        nearestRes: snap.sr?.nearestRes ?? null,
        nearestSup: snap.sr?.nearestSup ?? null,
        slBuffer: cfg.journalSlPips * cfg.pipSize,
        barLow: bar.l,
        barHigh: bar.h,
        signals: snap.signals,
        cfg,
        setupLevels: snap.tradeLevels,
        m30: bundle.m30,
      },
      { maxJournalRows: 5000 }
    );
    saveJournal(next.rows);
    console.error(`[forward-demo] EXEC ${symbol} ${intent.side} ${intent.setup} vol=${volume} · ${r.summary}`);
    void publishTradeExecuted({
      symbol,
      direction: intent.side === 'BUY' ? 'long' : 'short',
      lotSize: volume,
      entryPrice: intent.entry ?? bar.c,
      filledPrice: intent.entry ?? bar.c,
      stopLoss: intent.sl,
      takeProfit: intent.tp1,
      setup: intent.setup,
      barTimeMs: bar.t,
      filtersPassed: ['risk_gating'],
      brokerConnected: status.connected,
    });
  } else {
    const reason = recordApiFailure(safety, `order: ${r.summary}`);
    if (reason) {
      appendSafetyLog(reason, { failsafe: true });
      console.error(`[forward-demo] FAILSAFE: ${reason}`);
    } else {
      console.error(`[forward-demo] FAIL ${r.summary}`);
    }
  }
  saveSession(session);
  saveSafetyState(safety);
}

async function main() {
  process.env.STRATEGY_FREEZE = '1';
  let check = verifyFrozenStrategy(BACKEND_ROOT, productionFrozenConfig());
  if (!check.ok && process.env.STRATEGY_AUTO_FREEZE !== '0') {
    try {
      const { execSync } = await import('node:child_process');
      execSync('npm run strategy:freeze', { cwd: BACKEND_ROOT, stdio: 'pipe' });
      check = verifyFrozenStrategy(BACKEND_ROOT, productionFrozenConfig());
    } catch {
      /* keep original check */
    }
  }
  if (!check.ok) {
    console.error('Strategy freeze FAILED — run npm run strategy:freeze');
    check.errors.forEach((e) => console.error(`  ${e}`));
    process.exit(2);
  }

  const pollSec = Math.max(15, parseInt(readArg('poll-sec', String(POLL_SEC_DEFAULT)), 10) || POLL_SEC_DEFAULT);
  const safetyBoot = loadSafetyState();
  const isDry = effectiveDryRun(safetyBoot);

  let session = loadSession();
  const now = Date.now();
  let symbols: string[] = [];
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      symbols = await fetchBrokerSymbols();
      if (symbols.length) break;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[forward-demo] symbol list attempt ${attempt + 1}: ${msg}`);
    }
    if (attempt < 5) await new Promise((r) => setTimeout(r, 4000));
  }
  if (!symbols.length) {
    console.error('[forward-demo] using fallback symbol list (bridge symbols API unavailable)');
    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'DOGEUSDT'];
  }

  if (!session || now >= session.endMs) {
    const startMs = now;
    const endMs = startMs + DAYS * 86400000;
    const st = await brokerStatus(symbols[0]!);
    if (!st.connected) {
      console.error(`[forward-demo] ${BROKER_LABEL} not connected — waiting for app login or env keys`);
      session = {
        startedAt: new Date(startMs).toISOString(),
        endsAt: new Date(endMs).toISOString(),
        startMs,
        endMs,
        lastClosedBarT: null,
        lastClosedBarTBySymbol: {},
        symbolCursor: 0,
        lastEquitySnapMs: 0,
        tradeCountToday: 0,
        nyDay: null,
        server: null,
        dryRun: isDry,
      };
      saveSession(session);
    } else {
      session = {
        startedAt: new Date(startMs).toISOString(),
        endsAt: new Date(endMs).toISOString(),
        startMs,
        endMs,
        lastClosedBarT: null,
        lastClosedBarTBySymbol: {},
        symbolCursor: 0,
        lastEquitySnapMs: 0,
        tradeCountToday: 0,
        nyDay: null,
        server: st.server,
        dryRun: isDry,
      };
      saveSession(session);
      logEquitySnapshot(st.equity, { event: 'SESSION_START', server: st.server, endsAt: session.endsAt });
      console.error(`[forward-demo] Session started → ${session.endsAt}`);
      console.error(`[forward-demo] Server: ${st.server} · equity $${st.equity.toFixed(2)}`);
      console.error(`[forward-demo] Log: ${forwardDemoLogPath()}`);
      console.error(`[forward-demo] Broker: ${BROKER_LABEL} · ${symbols.length} USDT-M symbols (max ${MAX_FORWARD_SYMBOLS})`);
      if (isDry) console.error(`[forward-demo] DRY-RUN — no ${BROKER_LABEL} orders`);
    }
  } else {
    session.dryRun = isDry;
    if (!session.lastClosedBarTBySymbol) session.lastClosedBarTBySymbol = {};
    saveSession(session);
    console.error(`[forward-demo] Resuming session → ${session.endsAt}`);
  }

  const dryLabel = isDry
    ? envDryRunEnabled()
      ? 'FORWARD_DRY_RUN=1'
      : safetyBoot.failsafe
        ? 'failsafe'
        : 'CLI --dry-run'
    : 'LIVE ORDERS ENABLED';
  console.error(`[forward-demo] Poll every ${pollSec}s · risk ${(RISK_PCT * 100).toFixed(2)}% · ${BROKER_LABEL} · ${dryLabel}`);

  const runTick = async () => {
    const s = loadSession();
    if (!s) return;
    let syms = symbols;
    try {
      if (Date.now() - brokerSymbolsLoadedAt > 3600_000) syms = await fetchBrokerSymbols();
    } catch {
      /* keep last list */
    }
    const sym = nextSymbol(s, syms);
    if (!sym) return;
    await tickOnce(s, sym);
    saveSession(s);
  };

  await runTick();
  setInterval(() => {
    void runTick().catch((e) => {
      console.error('[forward-demo] tick error:', e instanceof Error ? e.message : e);
    });
  }, pollSec * 1000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
