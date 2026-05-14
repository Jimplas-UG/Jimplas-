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
import { computeGatesAndSignals, leftSideScan } from './signalEngine';
import { applyJournalSignalThrottle } from './signalThrottle';
import { buildTradeRecommendation } from './tradeBot';
import { clampTp1ForJournal } from './tradeGeometry';

export type JournalState = {
  rows: TradeJournalRow[];
  count: number;
};

export function resolveJournalOnBar(rows: TradeJournalRow[], bar: Bar, barIndex: number): TradeJournalRow[] {
  return rows.map((row) => {
    if (row.out !== 'OPEN' || row.tp1 == null || !Number.isFinite(row.tp1)) return row;
    if (barIndex <= row.barIndex) return row;
    if (row.dir === 'BUY') {
      if (bar.l <= row.sl) return { ...row, out: 'LOSS' };
      if (bar.h >= row.tp1) return { ...row, out: 'WIN' };
    } else {
      if (bar.h >= row.sl) return { ...row, out: 'LOSS' };
      if (bar.l <= row.tp1) return { ...row, out: 'WIN' };
    }
    return row;
  });
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
    signals: { p1Buy: boolean; p1Sell: boolean; p2Buy: boolean; p2Sell: boolean; p3Buy: boolean; p3Sell: boolean };
    /** When set, TP1 is clamped like {@link buildTradeRecommendation} (profit side + min/max reward pips). */
    cfg?: BilshenzEngineConfig;
  },
  opts?: { maxJournalRows?: number }
): JournalState {
  const { anyBuy, anySell, barIndex, timeStr, close, nearestRes, nearestSup, slBuffer, signals, cfg } = args;
  const maxJournalRows = opts?.maxJournalRows ?? 20;
  if (!anyBuy && !anySell) return prev;
  const isB = anyBuy;
  const stype = signals.p1Buy || signals.p1Sell ? 'P1' : signals.p2Buy || signals.p2Sell ? 'P2' : 'P3';
  const sSl = isB ? close - slBuffer : close + slBuffer;
  const rawTp1 = isB ? nearestRes : nearestSup;
  const sTp1 =
    cfg != null
      ? clampTp1ForJournal(isB ? 'BUY' : 'SELL', close, sSl, rawTp1, cfg)
      : rawTp1;
  const row: TradeJournalRow = {
    entry: close,
    sl: sSl,
    tp1: sTp1,
    dir: isB ? 'BUY' : 'SELL',
    type: stype as 'P1' | 'P2' | 'P3',
    time: timeStr,
    out: 'OPEN',
    barIndex,
  };
  const next = [row, ...prev.rows].slice(0, maxJournalRows);
  return { rows: next, count: Math.min(prev.count + 1, maxJournalRows) };
}

/** Manual Execute: one open row from the live trade bot snapshot (same geometry as auto journal). */
export function buildManualJournalEntry(args: {
  trade: TradeRecommendation;
  barIndex: number;
  timeStr: string;
}): TradeJournalRow | null {
  const t = args.trade;
  if (!t.side || t.entry == null || !Number.isFinite(t.entry) || t.sl == null || !Number.isFinite(t.sl)) return null;
  if (t.tp1 == null || !Number.isFinite(t.tp1)) return null;
  const typ = t.setup === 'P2' ? 'P2' : t.setup === 'P3' ? 'P3' : 'P1';
  return {
    entry: t.entry,
    sl: t.sl,
    tp1: t.tp1,
    dir: t.side,
    type: typ,
    time: args.timeStr,
    out: 'OPEN',
    barIndex: args.barIndex,
  };
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
    } else if (r.out === 'LOSS') {
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

  const bias = computeBias(h4, d1, close, m30);
  const sr = replaySrEngine(m30, cfg);

  const hasStructure = sr.nearestRes != null || sr.nearestSup != null;
  const structureOk = hasStructure;

  const range = leftSideScan({
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

  const resolvedJournal = resolveJournalOnBar(journalRows, m30[idx], idx);

  const { gates, signals: rawSignals } = computeGatesAndSignals({
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
  const signals = applyJournalSignalThrottle({
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
    structureLevels: levels,
    dxyClose,
    us10yClose,
    labelGap,
    slBuffer,
  };
}
