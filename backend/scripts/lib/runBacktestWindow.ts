/**
 * Shared live-profile backtest for audit / walk-forward (M30 bars already loaded).
 */
import type { Bar, BilshenzEngineConfig, TradeJournalRow } from '../../engine/types';
import {
  buildBundleFromM30Bars,
  computeBias,
  computeRisk,
  defaultBilshenzConfig,
  pushJournalRow,
  resolveJournalOnBar,
  resolveOutcomeForward,
  sliceMarketBundleToM30End,
  winRateFromJournal,
} from '../../engine';
import { atr, lastFinite } from '../../engine/indicators';
import { nyYmdKey, sessionFromUtcEpochMs } from '../../engine/sessionEngine';
import { replaySrBarByBar } from '../../engine/srEngine';
import { computeGatesAndSignalsJimplasFluidity } from '../../engine/jimplasFluiditySignalEngine';
import { m30ToM15Bars } from '../../engine/m15Bars';
import { leftSideScanPineV5 } from '../../engine/pineV5SignalEngine';
import {
  equityAfterAutoTrades,
  maxDrawdownFromSeries,
  type RealisticCosts,
} from './journalEquityPath';

const WARMUP = 80;
const MAX_JOURNAL = 200_000;

export type BacktestWindowResult = {
  netPct: number;
  endEquity: number;
  maxDd: number;
  trades: number;
  wins: number;
  losses: number;
  profitFactor: number;
  closed: TradeJournalRow[];
};

export function liveProfileCfg(overrides: Partial<BilshenzEngineConfig> = {}): BilshenzEngineConfig {
  return {
    ...defaultBilshenzConfig,
    maxDailyTrades: 3,
    usePineV5: true,
    enableP1: true,
    enableP2: true,
    enableP3: true,
    journalSlPips: 2,
    currentSpreadPips: 1.5,
    newsActive: false,
    nfpBlackout: false,
    geoRisk: 'LOW',
    showHistory: false,
    showHistoryMode: false,
    useLegacyTpClampOnly: true,
    p2UseStrictFilters: false,
    tpClampMinRiskReward: 1,
    tpClampSlFraction: 0,
    maxSlPipsForEntry: 0,
    journalSizingSlPips: 20,
    riskScaleWideStops: false,
    signalOnClosedBarOnly: true,
    ...overrides,
  };
}

function biasForBarSlice(sub: ReturnType<typeof sliceMarketBundleToM30End>) {
  const m30 = sub.m30;
  const close = m30[m30.length - 1]!.c;
  return computeBias(sub.h4, sub.d1, close);
}

function riskForBarSlice(sub: ReturnType<typeof sliceMarketBundleToM30End>, cfg: BilshenzEngineConfig) {
  const m30 = sub.m30;
  const close = m30[m30.length - 1]!.c;
  const atrArr = atr(m30, cfg.atrLen);
  const atrVal = lastFinite(atrArr);
  const dxy = sub.dxyCloseSeries;
  const dxyClose = dxy.length ? dxy[dxy.length - 1]! : null;
  const dxyClose3 = dxy.length > 3 ? dxy[dxy.length - 4]! : dxyClose;
  const uy = sub.us10yCloseSeries;
  const us10yClose = uy.length ? uy[uy.length - 1]! : null;
  return computeRisk(m30, sub.h4, cfg, atrVal, dxyClose ?? null, dxyClose3 ?? null, us10yClose ?? null, close);
}

export function runBacktestWindow(
  m30All: Bar[],
  rangeStartMs: number,
  rangeEndMs: number,
  startEquity: number,
  riskPct: number,
  cfg: BilshenzEngineConfig,
  realistic: RealisticCosts | null
): BacktestWindowResult {
  const base = buildBundleFromM30Bars(m30All);
  const srSeries = replaySrBarByBar(base.m30, cfg);
  let journalRows: TradeJournalRow[] = [];
  let tradeCount = 0;
  let lastBarSig: number | null = null;
  let nyDay: string | null = null;
  let runningEquity = startEquity;
  let peakEquityTrack = startEquity;
  let dayStartEquityTrack = startEquity;
  let lastClosedN = 0;
  const duplicateBarSignals: number[] = [];

  const m30 = base.m30;
  const m15 = m30ToM15Bars(m30);
  const journalCtx = { m30, m15, cfg };
  const fullBundle = base;

  for (let idx = WARMUP; idx < m30.length; idx++) {
    const bar = m30[idx]!;
    journalRows = resolveJournalOnBar(journalRows, bar, idx, journalCtx);
    if (bar.t < rangeStartMs || bar.t >= rangeEndMs) continue;

    const ymd = nyYmdKey(bar.t);
    if (nyDay !== ymd) {
      nyDay = ymd;
      tradeCount = 0;
      dayStartEquityTrack = runningEquity;
    }

    const closedSoFar = journalRows.filter((r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS');
    if (closedSoFar.length !== lastClosedN) {
      lastClosedN = closedSoFar.length;
      const { endEquity } = equityAfterAutoTrades(
        closedSoFar,
        cfg.pipSize,
        cfg.simUsdPerEnginePip,
        startEquity,
        riskPct,
        cfg,
        null
      );
      runningEquity = endEquity;
      peakEquityTrack = Math.max(peakEquityTrack, runningEquity);
    }

    const sr = srSeries[idx]!;
    const sub = sliceMarketBundleToM30End(fullBundle, idx);
    const bias = biasForBarSlice(sub);
    const risk = riskForBarSlice(sub, cfg);
    const hasStructure = !(sr.r1 == null && sr.r2 == null && sr.r3 == null && sr.s1 == null && sr.s2 == null && sr.s3 == null);
    const range = leftSideScanPineV5({
      nearestRes: sr.nearestRes,
      nearestSup: sr.nearestSup,
      close: bar.c,
      pip: cfg.pipSize,
      m30,
      idx,
      minPips: cfg.minRangePips,
    });
    const session = sessionFromUtcEpochMs(bar.t);
    const prevSession = idx >= 1 ? sessionFromUtcEpochMs(m30[idx - 1]!.t) : session;
    const atrArr = atr(m30, cfg.atrLen);
    const atrVal = lastFinite(atrArr);
    const { signals } = computeGatesAndSignalsJimplasFluidity({
      cfg,
      inSession: session.inSession,
      session,
      prevInSession: prevSession.inSession,
      hasStructure,
      structureOk: hasStructure,
      dailyTradeCount: tradeCount,
      risk,
      bias,
      sr,
      m30,
      h4: sub.h4,
      idx,
      atrVal,
    });

    const sig = signals.anyBuy || signals.anySell;
    if (sig && lastBarSig === bar.t) duplicateBarSignals.push(bar.t);
    if (sig && lastBarSig !== bar.t && tradeCount < cfg.maxDailyTrades) {
      let riskHalted = false;
      if (cfg.maxDailyLossPct > 0 && dayStartEquityTrack > 0) {
        const dayLossPct = ((dayStartEquityTrack - runningEquity) / dayStartEquityTrack) * 100;
        if (dayLossPct >= cfg.maxDailyLossPct) riskHalted = true;
      }
      if (!riskHalted && cfg.maxDrawdownPct > 0 && peakEquityTrack > 0) {
        const ddPct = ((peakEquityTrack - runningEquity) / peakEquityTrack) * 100;
        if (ddPct >= cfg.maxDrawdownPct) riskHalted = true;
      }
      if (riskHalted) {
        lastBarSig = bar.t;
        continue;
      }
      const slBuffer = cfg.journalSlPips * cfg.pipSize;
      const prev = { rows: journalRows, count: journalRows.length };
      const next = pushJournalRow(
        prev,
        {
          anyBuy: signals.anyBuy,
          anySell: signals.anySell,
          barIndex: idx,
          timeStr: new Date(bar.t).toISOString(),
          close: bar.c,
          nearestRes: sr.nearestRes,
          nearestSup: sr.nearestSup,
          slBuffer,
          barLow: bar.l,
          barHigh: bar.h,
          signals,
          cfg,
          setupLevels: {},
          m30,
        },
        { maxJournalRows: MAX_JOURNAL }
      );
      journalRows = next.rows;
      tradeCount += 1;
      lastBarSig = bar.t;
    }
  }

  const resolved = journalRows.map((r) => (r.out !== 'OPEN' ? r : resolveOutcomeForward(m30, m15, r, cfg)));
  const inRange = (r: TradeJournalRow) => {
    const bi = r.barIndex;
    if (bi < 0 || bi >= m30.length) return false;
    const t = m30[bi]!.t;
    return t >= rangeStartMs && t < rangeEndMs;
  };
  const resolvedInRange = resolved.filter(inRange);
  const closed = resolvedInRange.filter((r) => r.out === 'WIN' || r.out === 'LOSS' || r.out === 'HALF_LOSS');
  const closedChrono = [...closed].sort((a, b) => a.barIndex - b.barIndex);
  const wr = winRateFromJournal(resolvedInRange);
  const { endEquity, series } = equityAfterAutoTrades(
    closedChrono,
    cfg.pipSize,
    cfg.simUsdPerEnginePip,
    startEquity,
    riskPct,
    cfg,
    realistic
  );
  const maxDd = maxDrawdownFromSeries(startEquity, series);
  const netPct = ((endEquity - startEquity) / startEquity) * 100;
  let grossWin = 0;
  let grossLoss = 0;
  for (const s of series) {
    if (s.pnl > 0) grossWin += s.pnl;
    else grossLoss += -s.pnl;
  }
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 99 : 0;

  return {
    netPct,
    endEquity,
    maxDd,
    trades: closed.length,
    wins: wr.totalWins,
    losses: wr.totalLosses,
    profitFactor,
    closed: closedChrono,
  };
}
