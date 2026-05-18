import type {
  Bar,
  BilshenzEngineConfig,
  BilshenzSnapshot,
  MarketBundle,
  TradeJournalRow,
  TradeRecommendation,
  WinRateSnapshot,
} from './types';
import { atr, lastFinite } from './indicators';
import { computeBias } from './biasEngine';
import { monthlyPrevHl, pdhPdl, weeklyPrevHl } from './structureEngine';
import { sessionFromUtcEpochMs } from './sessionEngine';
import { replaySrEngine } from './srEngine';
import { computeRisk } from './riskEngine';
import { wickMetricsAt } from './wickEngine';
import { computeGatesAndSignalsJimplasFluidity } from './jimplasFluiditySignalEngine';
import { computeGatesAndSignals, leftSideScan } from './signalEngine';
import { leftSideScanPineV5 } from './pineV5SignalEngine';
import { applyJournalSignalThrottle } from './signalThrottle';
import { buildTradeRecommendation } from './tradeBot';
import { applyBalancedClampGeometry, clampTp1ForJournal, slPipsFromEntry } from './tradeGeometry';
import { closedM15BarsInWindow, M15_MS, M30_MS } from './m15Bars';
import { armM15ExitWatch, halfLossExitPrice, isAdverseM15Close, underwaterRiskFraction } from './m15AdverseExit';
import { m30ToM15Bars } from './m15Bars';

export type JournalState = {
  rows: TradeJournalRow[];
  count: number;
};

export type JournalResolveContext = {
  m30: Bar[];
  m15: Bar[];
  cfg: BilshenzEngineConfig;
};

function applyM15AdverseExit(
  row: TradeJournalRow,
  m15: Bar[],
  m30: Bar[],
  barIndex: number,
  cfg: BilshenzEngineConfig
): TradeJournalRow {
  if (row.out !== 'OPEN' || !row.m15ExitWatch) return row;
  const entryMs = m30[row.barIndex]!.t;
  const afterMs = row.m15CheckedThroughMs ?? entryMs;
  const upToCloseMs = m30[barIndex]!.t + M30_MS;
  const window = closedM15BarsInWindow(m15, afterMs, upToCloseMs);
  let checkedThrough = afterMs;
  for (const m15b of window) {
    checkedThrough = m15b.t + M15_MS;
    const minPct = cfg.m15MinRiskPctBeforeExit;
    const underwater = underwaterRiskFraction(row, m15b.c) >= minPct;
    if (isAdverseM15Close(row, m15b) && underwater) {
      return {
        ...row,
        out: 'HALF_LOSS',
        exitPrice: halfLossExitPrice(row),
        m15CheckedThroughMs: checkedThrough,
      };
    }
  }
  if (checkedThrough > afterMs) {
    return { ...row, m15CheckedThroughMs: checkedThrough };
  }
  return row;
}

export function resolveJournalOnBar(
  rows: TradeJournalRow[],
  bar: Bar,
  barIndex: number,
  ctx?: JournalResolveContext
): TradeJournalRow[] {
  return rows.map((row) => {
    if (row.out !== 'OPEN' || row.tp1 == null || !Number.isFinite(row.tp1)) return row;
    if (barIndex <= row.barIndex) return row;

    let r = row;
    if (ctx?.cfg.enableM15AdverseExit && ctx.m15.length > 0) {
      r = applyM15AdverseExit(r, ctx.m15, ctx.m30, barIndex, ctx.cfg);
      if (r.out !== 'OPEN') return r;
    }

    if (r.dir === 'BUY') {
      if (bar.l <= r.sl) return { ...r, out: 'LOSS' };
      if (r.tp1 != null && bar.h >= r.tp1) return { ...r, out: 'WIN' };
    } else {
      if (bar.h >= r.sl) return { ...r, out: 'LOSS' };
      if (r.tp1 != null && bar.l <= r.tp1) return { ...r, out: 'WIN' };
    }
    return r;
  });
}

/** Walk forward from entry to end (backtest / final open rows). */
export function resolveOutcomeForward(
  m30: Bar[],
  m15: Bar[],
  row: TradeJournalRow,
  cfg: BilshenzEngineConfig
): TradeJournalRow {
  let r = row;
  for (let i = row.barIndex + 1; i < m30.length; i++) {
    const [next] = resolveJournalOnBar([r], m30[i]!, i, { m30, m15, cfg });
    r = next!;
    if (r.out !== 'OPEN') return r;
  }
  return r;
}

export function pushJournalRow(
  prev: JournalState,
  args: {
    anyBuy: boolean;
    anySell: boolean;
    barIndex: number;
    timeStr: string;
    close: number;
    nearestRes: number | null;
    nearestSup: number | null;
    slBuffer: number;
    barLow?: number;
    barHigh?: number;
    signals: { p1Buy: boolean; p1Sell: boolean; p2Buy: boolean; p2Sell: boolean; p3Buy: boolean; p3Sell: boolean };
    cfg?: BilshenzEngineConfig;
    /** Jimplas Fluidity per-setup SL/TP (overrides nearest S/R + wick SL when set). */
    setupLevels?: { setup: 'P1' | 'P2' | 'P3'; entry: number; sl: number; tp1: number } | null;
    m30?: Bar[];
  },
  opts?: { maxJournalRows?: number }
): JournalState {
  const { anyBuy, anySell, barIndex, timeStr, close, nearestRes, nearestSup, slBuffer, barLow, barHigh, signals, cfg, setupLevels } =
    args;
  const maxJournalRows = opts?.maxJournalRows ?? 20;
  if (!anyBuy && !anySell) return prev;
  const isB = anyBuy;
  const stype =
    setupLevels?.setup ??
    (signals.p1Buy || signals.p1Sell ? 'P1' : signals.p2Buy || signals.p2Sell ? 'P2' : 'P3');
  let entryPx = close;
  let sSl: number;
  let rawTp1: number | null;
  if (setupLevels != null) {
    entryPx = close;
    sSl = setupLevels.sl;
    rawTp1 = setupLevels.tp1;
  } else {
    const pineSl = cfg?.usePineV5 !== false;
    sSl = isB
      ? (pineSl && barLow != null ? barLow : close) - slBuffer
      : (pineSl && barHigh != null ? barHigh : close) + slBuffer;
    rawTp1 = isB ? nearestRes : nearestSup;
  }

  const side = isB ? 'BUY' : 'SELL';
  const st = stype as 'P1' | 'P2' | 'P3';
  let sTp1: number | null = rawTp1;
  if (cfg != null) {
    if (cfg.maxSlPipsForEntry > 0) {
      const slP = slPipsFromEntry(side, entryPx, sSl, cfg.pipSize);
      if (slP > cfg.maxSlPipsForEntry) return prev;
    }
    if (cfg.useLegacyTpClampOnly && cfg.tpClampSlFraction > 0) {
      const bal = applyBalancedClampGeometry(side, entryPx, sSl, rawTp1, st, cfg);
      sSl = bal.sl;
      sTp1 = bal.tp1;
    } else if (cfg.useLegacyTpClampOnly) {
      sTp1 = clampTp1ForJournal(side, entryPx, sSl, rawTp1, cfg);
    } else {
      sTp1 = clampTp1ForJournal(side, entryPx, sSl, rawTp1, cfg);
    }
  }

  let row: TradeJournalRow = {
    entry: entryPx,
    sl: sSl,
    tp1: sTp1,
    dir: isB ? 'BUY' : 'SELL',
    type: stype as 'P1' | 'P2' | 'P3',
    time: timeStr,
    out: 'OPEN',
    barIndex,
  };
  if (cfg && args.m30?.length) {
    row = armM15ExitWatch(row, args.m30, cfg);
  }
  const next = [row, ...prev.rows].slice(0, maxJournalRows);
  return { rows: next, count: Math.min(prev.count + 1, maxJournalRows) };
}

/** Manual Execute: one open row from the live trade bot snapshot (same geometry as auto journal). */
export function buildManualJournalEntry(args: {
  trade: TradeRecommendation;
  barIndex: number;
  timeStr: string;
  m30?: Bar[];
  cfg?: BilshenzEngineConfig;
}): TradeJournalRow | null {
  const t = args.trade;
  if (!t.side || t.entry == null || !Number.isFinite(t.entry) || t.sl == null || !Number.isFinite(t.sl)) return null;
  if (t.tp1 == null || !Number.isFinite(t.tp1)) return null;
  const typ = t.setup === 'P2' ? 'P2' : t.setup === 'P3' ? 'P3' : 'P1';
  let row: TradeJournalRow = {
    entry: t.entry,
    sl: t.sl,
    tp1: t.tp1,
    dir: t.side,
    type: typ,
    time: args.timeStr,
    out: 'OPEN',
    barIndex: args.barIndex,
  };
  if (args.cfg && args.m30?.length) {
    row = armM15ExitWatch(row, args.m30, args.cfg);
  }
  return row;
}

export function winRateFromJournal(rows: TradeJournalRow[]): WinRateSnapshot {
  return tally(rows);
}

function tally(rows: TradeJournalRow[]): WinRateSnapshot {
  let totalWins = 0;
  let totalLosses = 0;
  let p1w = 0,
    p1l = 0,
    p2w = 0,
    p2l = 0,
    p3w = 0,
    p3l = 0;
  for (const r of rows) {
    if (r.out === 'WIN') {
      totalWins += 1;
      if (r.type === 'P1') p1w += 1;
      if (r.type === 'P2') p2w += 1;
      if (r.type === 'P3') p3w += 1;
    } else if (r.out === 'LOSS' || r.out === 'HALF_LOSS') {
      totalLosses += 1;
      if (r.type === 'P1') p1l += 1;
      if (r.type === 'P2') p2l += 1;
      if (r.type === 'P3') p3l += 1;
    }
  }
  const closed = totalWins + totalLosses;
  const winRatePct = closed > 0 ? (totalWins / closed) * 100 : 0;
  const p1Wr = p1w + p1l > 0 ? (p1w / (p1w + p1l)) * 100 : 0;
  const p2Wr = p2w + p2l > 0 ? (p2w / (p2w + p2l)) * 100 : 0;
  const p3Wr = p3w + p3l > 0 ? (p3w / (p3w + p3l)) * 100 : 0;
  return {
    totalWins,
    totalLosses,
    winRatePct,
    p1Wr,
    p2Wr,
    p3Wr,
    journal: rows,
  };
}

export type ComputeArgs = {
  bundle: MarketBundle;
  cfg: BilshenzEngineConfig;
  dailyTradeCount: number;
  journalRows: TradeJournalRow[];
  nowUtcMs: number;
};

export function computeBilshenzSnapshot(args: ComputeArgs): BilshenzSnapshot {
  const { bundle, cfg, dailyTradeCount, journalRows, nowUtcMs } = args;
  const m30 = bundle.m30;
  const h4 = bundle.h4;
  const d1 = bundle.d1;
  const w1 = bundle.w1;
  const mn1 = bundle.mn1;
  const n = m30.length;
  const idx = n - 1;
  const close = m30[idx].c;

  const session = sessionFromUtcEpochMs(nowUtcMs);
  const atrArr = atr(m30, cfg.atrLen);
  const atrVal = lastFinite(atrArr);
  const labelGap = atrVal != null ? atrVal * 0.3 : 0;
  const slBuffer = cfg.journalSlPips * cfg.pipSize;

  const usePine = cfg.usePineV5 !== false;
  const bias = computeBias(h4, d1, close, m30);
  const sr = replaySrEngine(m30, cfg);

  const hasStructure = usePine
    ? !(sr.r1 == null && sr.r2 == null && sr.r3 == null && sr.s1 == null && sr.s2 == null && sr.s3 == null)
    : sr.nearestRes != null || sr.nearestSup != null;
  const structureOk = hasStructure;

  const range = usePine
    ? leftSideScanPineV5({
        nearestRes: sr.nearestRes,
        nearestSup: sr.nearestSup,
        close,
        pip: cfg.pipSize,
        m30,
        idx,
        minPips: cfg.minRangePips,
      })
    : leftSideScan({
        immRes: sr.nearestRes,
        immSup: sr.nearestSup,
        close,
        pip: cfg.pipSize,
        m30,
        idx,
        minPips: cfg.minRangePips,
        lsBars: cfg.leftScanBars,
        lsChopMax: cfg.leftScanMaxChop,
      });

  const dxySeries = bundle.dxyCloseSeries;
  const dxyClose = dxySeries.length ? dxySeries[dxySeries.length - 1] : null;
  const dxyClose3 = dxySeries.length > 3 ? dxySeries[dxySeries.length - 4] : dxySeries.length ? dxySeries[0] : null;
  const us10ySeries = bundle.us10yCloseSeries;
  const us10yClose = us10ySeries.length ? us10ySeries[us10ySeries.length - 1] : null;

  const risk = computeRisk(m30, h4, cfg, atrVal, dxyClose, dxyClose3, us10yClose, close);

  const wick = wickMetricsAt(m30, idx);

  const m15 = m30ToM15Bars(m30);
  const resolvedJournal = resolveJournalOnBar(journalRows, m30[idx], idx, {
    m30,
    m15,
    cfg,
  });

  const prevSession = idx >= 1 ? sessionFromUtcEpochMs(m30[idx - 1]!.t) : session;
  const jimplasResult = usePine
    ? computeGatesAndSignalsJimplasFluidity({
        cfg,
        inSession: session.inSession,
        session,
        prevInSession: prevSession.inSession,
        hasStructure,
        structureOk,
        dailyTradeCount,
        risk,
        bias,
        sr,
        m30,
        h4,
        idx,
        atrVal,
      })
    : null;

  const { gates, signals: rawSignals } = jimplasResult
    ? { gates: jimplasResult.gates, signals: jimplasResult.signals }
    : computeGatesAndSignals({
        cfg,
        inSession: session.inSession,
        structureOk,
        hasStructure,
        dailyTradeCount,
        risk,
        bias,
        sr,
        range,
        wick,
        m30,
        idx,
      });

  const sessionOk = session.inSession || cfg.showHistory;
  const signals = usePine
    ? rawSignals
    : applyJournalSignalThrottle({
        cfg,
        m30,
        idx,
        signals: rawSignals,
        journalRows: resolvedJournal,
        aggregateDeps: {
          sessionOk,
          maxTradesReached: gates.maxTradesReached,
          newsActive: cfg.newsActive,
          nfpBlackout: cfg.nfpBlackout,
          spreadBlocked: risk.spreadBlocked,
          dxyBlocksBuy: risk.dxyBlocksBuy,
          athZoneBlocked: risk.athZoneBlocked,
          geoHigh: risk.geoHigh,
        },
      });

  const winRate = tally(resolvedJournal);

  const openRow = resolvedJournal.find((r) => r.out === 'OPEN') ?? null;

  const trade = buildTradeRecommendation({
    cfg,
    session,
    gates,
    risk,
    signals,
    close,
    nearestRes: sr.nearestRes,
    nearestSup: sr.nearestSup,
    slBuffer,
    bullClean: range.bullClean,
    bearClean: range.bearClean,
    barLow: m30[idx].l,
    barHigh: m30[idx].h,
    setupLevels: jimplasResult?.levels ?? null,
    openJournalRow: openRow,
    m30,
    m15,
  });

  const levels = { ...pdhPdl(d1), ...weeklyPrevHl(w1), ...monthlyPrevHl(mn1) };

  return {
    asOf: nowUtcMs,
    session,
    bias,
    sr: { ...sr, zonePip: cfg.zoneHalfWidthPips * cfg.pipSize },
    range,
    wick,
    risk,
    gates,
    signals,
    winRate,
    trade,
    tradeLevels: jimplasResult?.levels ?? null,
    structureLevels: levels,
    dxyClose,
    us10yClose,
    labelGap,
    slBuffer,
  };
}
