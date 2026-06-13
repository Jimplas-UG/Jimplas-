/**
 * Headless 30-day Exness demo forward test — frozen config, live MT5 feed, real demo orders.
 *
 * Prerequisites: Exness MT5 logged in + npm run mt5-api (8765)
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

const BROKER_MODE = (process.env.BROKER_MODE ?? 'mt5').trim().toLowerCase();
const USE_BINANCE = BROKER_MODE === 'binance' || BROKER_MODE === 'paper';
const BROKER_LABEL = USE_BINANCE ? (BROKER_MODE === 'paper' ? 'Binance paper' : 'Binance') : 'MT5';
const MT5_API = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const BINANCE_API = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const BROKER_API = USE_BINANCE ? BINANCE_API : MT5_API;
const SYMBOL =
  process.env.BINANCE_SYMBOL?.trim() ||
  process.env.MT5_SYMBOL?.trim() ||
  (USE_BINANCE ? 'XAUUSDT' : 'XAUUSD');
const M30_MS = 30 * 60 * 1000;
const WARMUP_BARS = 200;
const RISK_PCT = Math.max(0.0001, Math.min(0.05, Number(process.env.RISK_PCT ?? '0.005') || 0.005));
const DAYS = 30;
const POLL_SEC_DEFAULT = Math.max(15, parseInt(process.env.FORWARD_POLL_SEC ?? '45', 10) || 45);

type SessionState = {
  startedAt: string;
  endsAt: string;
  startMs: number;
  endMs: number;
  lastClosedBarT: number | null;
  lastEquitySnapMs: number;
  tradeCountToday: number;
  nyDay: string | null;
  server: string | null;
  dryRun: boolean;
};

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

function orderIdempotencyKey(barT: number, side: string, setup: string): string {
  return `${barT}:${side}:${setup}`;
}

async function brokerStatus(): Promise<{
  connected: boolean;
  trade_allowed: boolean;
  equity: number;
  server: string | null;
  spreadPips: number;
  usdPerPip: number;
}> {
  const st = await fetch(`${BROKER_API}/api/status`);
  if (!st.ok) throw new Error(`${BROKER_LABEL} status HTTP ${st.status}`);
  const j = (await st.json()) as {
    connected?: boolean;
    account?: { equity?: number; server?: string; trade_allowed?: boolean };
    trade_allowed?: boolean;
  };
  let spreadPips = 3.08;
  let usdPerPip = 10;
  try {
    const specRes = await fetch(`${BROKER_API}/api/symbol/${encodeURIComponent(SYMBOL)}?pip_size=0.1`);
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

async function fetchM30Bars(fromMs: number, toMs: number): Promise<Bar[]> {
  const url = `${BROKER_API}/api/bars/${encodeURIComponent(SYMBOL)}?from_ms=${fromMs}&to_ms=${toMs}`;
  const res = await fetch(url);
  if (!res.ok) {
    if (USE_BINANCE) {
      const fallback = `${BROKER_API}/api/bars/${encodeURIComponent(SYMBOL)}?count=1500`;
      const res2 = await fetch(fallback);
      if (!res2.ok) throw new Error(`${BROKER_LABEL} bars ${res2.status}`);
      const j2 = (await res2.json()) as { bars?: Bar[] };
      return (j2.bars ?? []).filter((b) => Number.isFinite(b.t)).sort((a, b) => a.t - b.t);
    }
    throw new Error(`${BROKER_LABEL} bars ${res.status}`);
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
    mt5Connected: status.connected,
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
  equity: number,
  entry: number | null | undefined,
  sl: number | null | undefined,
  pipSize: number,
): Promise<number> {
  const riskUsd = equity * RISK_PCT;
  const spec = await fetchBinanceSymbolSpec(BINANCE_API, SYMBOL, pipSize);
  if (!spec || entry == null || sl == null) return spec?.minQty ?? 0.001;
  const qty = quantityFromRiskUsd(riskUsd, entry, sl, spec);
  return qty > 0 ? qty : spec.minQty;
}

async function tickOnce(session: SessionState): Promise<void> {
  const now = Date.now();
  if (now >= session.endMs) {
    console.error('[forward-demo] 30-day window complete');
    process.exit(0);
  }

  const safety = loadSafetyState();
  session.dryRun = effectiveDryRun(safety);

  if (safety.failsafe) {
    try {
      const probe = await brokerStatus();
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
    status = await brokerStatus();
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
    m30All = await fetchM30Bars(fetchFrom, now + M30_MS);
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
    console.error(`[forward-demo] Too few bars (${m30All.length})`);
    saveSafetyState(safety);
    return;
  }

  const bundle = buildBundleFromM30Bars(m30All);
  const n = bundle.m30.length;
  const signalIdx = cfg.signalOnClosedBarOnly !== false && n >= 2 ? n - 2 : n - 1;
  const bar = bundle.m30[signalIdx]!;

  if (session.lastClosedBarT === bar.t) {
    console.error(`[forward-demo] ${new Date().toISOString().slice(11, 19)} waiting for new M30 bar (last: ${new Date(bar.t).toISOString().slice(11, 16)})`);
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
      symbol: SYMBOL,
      blockedBy: ['daily_loss_limit'],
    });
    console.error(`[forward-demo] ${new Date(bar.t).toISOString()} blocked: daily loss limit`);
    session.lastClosedBarT = bar.t;
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

  session.lastClosedBarT = bar.t;
  saveJournal(journalRows);
  saveSession(session);
  saveSafetyState(safety);

  if (!gate.ok) {
    if (snap.signals?.anyBuy || snap.signals?.anySell) {
      logForwardMissed({ reason: gate.reason, barTimeMs: bar.t });
      void publishTradeBlocked({
        symbol: SYMBOL,
        direction: trade?.side === 'BUY' ? 'long' : trade?.side === 'SELL' ? 'short' : null,
        blockedBy: [gate.reason],
      });
    }
    console.error(`[forward-demo] ${new Date(bar.t).toISOString()} blocked: ${gate.reason}`);
    return;
  }

  const intent = buildBrokerOrderIntent(trade!, {
    barTimeMs: bar.t,
    runMode: 'live',
    trigger: 'auto',
    symbol: SYMBOL,
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
  const volume = USE_BINANCE
    ? await binanceQuantityForIntent(status.equity, intent.entry, intent.sl, cfg.pipSize)
    : lotsForRisk(status.equity, slPips, status.usdPerPip);
  const setup =
    intent.setup === 'P1' || intent.setup === 'P2' || intent.setup === 'P3' ? intent.setup : 'NONE';
  const idemKey = orderIdempotencyKey(bar.t, intent.side, setup);

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
    console.error(
      `[forward-demo] DRY (${why}) ${intent.side} ${intent.setup} @ ${intent.entry?.toFixed(2)} vol=${volume} bar=${new Date(bar.t).toISOString()}`
    );
    session.tradeCountToday += 1;
    session.dryRun = true;
    saveSession(session);
    saveSafetyState(safety);
    return;
  }

  const useBinance = USE_BINANCE;
  const riskUsd = status.equity * RISK_PCT;
  const r = await executeBrokerRoutes({
    intent,
    useMt5: !useBinance,
    mt5BaseUrl: MT5_API,
    mt5Volume: volume,
    useBinance,
    binanceBaseUrl: BINANCE_API,
    binanceQuantity: useBinance ? volume : undefined,
    riskUsd: useBinance ? riskUsd : undefined,
    symbol: SYMBOL,
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
    console.error(`[forward-demo] EXEC ${intent.side} ${intent.setup} vol=${volume} · ${r.summary}`);
    void publishTradeExecuted({
      symbol: SYMBOL,
      direction: intent.side === 'BUY' ? 'long' : 'short',
      lotSize: volume,
      entryPrice: intent.entry ?? bar.c,
      filledPrice: intent.entry ?? bar.c,
      stopLoss: intent.sl,
      takeProfit: intent.tp1,
      setup: intent.setup,
      barTimeMs: bar.t,
      filtersPassed: ['risk_gating'],
      mt5Connected: status.connected,
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
  const check = verifyFrozenStrategy(BACKEND_ROOT, productionFrozenConfig());
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
  if (!session || now >= session.endMs) {
    const startMs = now;
    const endMs = startMs + DAYS * 86400000;
    const st = await brokerStatus();
    if (!st.connected) {
      if (USE_BINANCE) {
        console.error('Start Binance bridge: cd binance_trading_system/python && .\\start-api.ps1');
        if (BROKER_MODE === 'paper') console.error('  Set BINANCE_PAPER=1 for simulated fills');
      } else {
        console.error('Start Exness MT5 + login, then: npm run mt5-api');
      }
      process.exit(1);
    }
    session = {
      startedAt: new Date(startMs).toISOString(),
      endsAt: new Date(endMs).toISOString(),
      startMs,
      endMs,
      lastClosedBarT: null,
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
    console.error(`[forward-demo] Broker: ${BROKER_LABEL} · symbol ${SYMBOL}`);
    if (isDry) console.error(`[forward-demo] DRY-RUN — no ${BROKER_LABEL} orders`);
  } else {
    session.dryRun = isDry;
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
    await tickOnce(s);
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
