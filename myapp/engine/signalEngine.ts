import type { Bar, BiasSnapshot, BilshenzEngineConfig, GateSnapshot, RangeCleanSnapshot, RiskSnapshot, SignalSnapshot } from './types';
import type { SrReplayResult } from './srEngine';
import { wickMetricsAt } from './wickEngine';

/** Recompute anyBuy / anySell from P1–P3 flags (Pine: requires in_session, not show_history). */
export function recomputeSignalAggregates(
  s: Pick<SignalSnapshot, 'p1Buy' | 'p1Sell' | 'p2Buy' | 'p2Sell' | 'p3Buy' | 'p3Sell'>,
  deps: {
    /** Pine any_buy/any_sell: in_session only. */
    sessionOk: boolean;
    maxTradesReached: boolean;
    newsActive: boolean;
    nfpBlackout: boolean;
    spreadBlocked: boolean;
    dxyBlocksBuy: boolean;
    athZoneBlocked: boolean;
    geoHigh: boolean;
  }
): Pick<SignalSnapshot, 'anyBuy' | 'anySell'> {
  const anyBuy =
    (s.p1Buy || s.p2Buy || s.p3Buy) &&
    deps.sessionOk &&
    !deps.maxTradesReached &&
    !deps.newsActive &&
    !deps.nfpBlackout &&
    !deps.spreadBlocked &&
    !deps.dxyBlocksBuy &&
    !deps.athZoneBlocked &&
    !deps.geoHigh;
  const anySell =
    (s.p1Sell || s.p2Sell || s.p3Sell) &&
    deps.sessionOk &&
    !deps.maxTradesReached &&
    !deps.newsActive &&
    !deps.nfpBlackout &&
    !deps.spreadBlocked &&
    !deps.geoHigh;
  return { anyBuy, anySell };
}

/** Pine Section 6 — left-side chop counts (current close vs imm levels). */
function lsBullChopCount(immRes: number | null, close: number, m30: Bar[], idx: number, lsBars: number): number {
  let n = 0;
  if (immRes == null) return 0;
  for (let i = 1; i <= lsBars; i++) {
    const j = idx - i;
    if (j < 0) break;
    const ci = m30[j].c;
    if (ci > close && ci < immRes) n += 1;
  }
  return n;
}

function lsBearChopCount(immSup: number | null, close: number, m30: Bar[], idx: number, lsBars: number): number {
  let n = 0;
  if (immSup == null) return 0;
  for (let i = 1; i <= lsBars; i++) {
    const j = idx - i;
    if (j < 0) break;
    const ci = m30[j].c;
    if (ci < close && ci > immSup) n += 1;
  }
  return n;
}

/** Pine v3.2 left-side scanner → ls_bull_ok / ls_bear_ok. */
export function leftSideScan(args: {
  immRes: number | null;
  immSup: number | null;
  close: number;
  pip: number;
  m30: Bar[];
  idx: number;
  minPips: number;
  lsBars: number;
  lsChopMax: number;
}): RangeCleanSnapshot {
  const { immRes, immSup, close, pip, m30, idx, minPips, lsBars, lsChopMax } = args;
  const distRes = immRes == null ? 0 : (immRes - close) / pip;
  const distSup = immSup == null ? 0 : (close - immSup) / pip;
  const bullRangeOk = immRes != null && distRes >= minPips;
  const bearRangeOk = immSup != null && distSup >= minPips;
  const bullChop = lsBullChopCount(immRes, close, m30, idx, lsBars);
  const bearChop = lsBearChopCount(immSup, close, m30, idx, lsBars);
  const bullClean = bullRangeOk && bullChop <= lsChopMax;
  const bearClean = bearRangeOk && bearChop <= lsChopMax;
  return {
    bullPips: distRes,
    bearPips: distSup,
    bullRangeOk,
    bearRangeOk,
    bullClean,
    bearClean,
    bullChop,
    bearChop,
  };
}

/** @deprecated Use leftSideScan — kept for external imports. */
export function rangeClean(
  nearestRes: number | null,
  nearestSup: number | null,
  close: number,
  pip: number,
  m30: Bar[],
  idx: number,
  minPips: number
): RangeCleanSnapshot {
  return leftSideScan({
    immRes: nearestRes,
    immSup: nearestSup,
    close,
    pip,
    m30,
    idx,
    minPips,
    lsBars: 40,
    lsChopMax: 3,
  });
}

/**
 * Pine v3.2 Section 9 — E1 wick sweep, E2 M30 breakout, E3 flip retest.
 * Bias / jimplas filters are not in Pine entries; M30 HTF bias is dashboard-only.
 */
export function computeGatesAndSignals(args: {
  cfg: BilshenzEngineConfig;
  inSession: boolean;
  hasStructure: boolean;
  structureOk: boolean;
  dailyTradeCount: number;
  risk: RiskSnapshot;
  bias: BiasSnapshot;
  sr: SrReplayResult;
  range: RangeCleanSnapshot;
  wick: ReturnType<typeof wickMetricsAt>;
  m30: Bar[];
  idx: number;
}): { gates: GateSnapshot; signals: SignalSnapshot } {
  const { cfg, inSession, hasStructure, structureOk, dailyTradeCount, risk, sr, range, wick, m30, idx } = args;

  const maxTradesReached = dailyTradeCount >= cfg.maxDailyTrades;
  const newsActive = cfg.newsActive;
  const nfpBlackout = cfg.nfpBlackout;
  const spreadBlocked = risk.spreadBlocked;
  const geoHigh = risk.geoHigh;

  const hardBlockBuy =
    newsActive || nfpBlackout || spreadBlocked || !structureOk || maxTradesReached || risk.dxyBlocksBuy || risk.athZoneBlocked || geoHigh;
  const hardBlockSell = newsActive || nfpBlackout || spreadBlocked || !structureOk || maxTradesReached || geoHigh;

  const masterBlock = cfg.showHistoryMode ? false : newsActive || nfpBlackout || spreadBlocked || !structureOk;
  const sessionGate = cfg.showHistory || inSession;
  const liveGateBuy = inSession && !hardBlockBuy && structureOk;
  const liveGateSell = inSession && !hardBlockSell && structureOk;

  const histBullOk = cfg.showHistory || range.bullClean;
  const histBearOk = cfg.showHistory || range.bearClean;

  const isDoji = wick.isDoji;
  const zone = cfg.zoneHalfWidthPips * cfg.pipSize;
  const wickP1 = cfg.p1WickRatioMin;
  const bodyP2 = cfg.p2BodyRatioMin;
  const e2Near = cfg.e2NearImmZonePips * cfg.pipSize;

  const immRes = sr.nearestRes;
  const immSup = sr.nearestSup;
  const flipSup = sr.flipSupLevel;
  const flipRes = sr.flipResLevel;

  const bullBar = m30[idx].c > m30[idx].o;
  const bearBar = m30[idx].c < m30[idx].o;

  const okLwk = wick.lowerWickRatio >= wickP1;
  const okUwk = wick.upperWickRatio >= wickP1;
  const okBody = wick.bodyRatio >= cfg.bodyRatioMin;
  const okBodyP2 = wick.bodyRatio >= bodyP2;
  const rLwk = wick.candleRange > 0 ? wick.lowerWick / wick.candleRange : 0;
  const rUwk = wick.candleRange > 0 ? wick.upperWick / wick.candleRange : 0;

  const sessionOrHist = cfg.showHistory || inSession;
  const pineGate =
    sessionOrHist && !spreadBlocked && !isDoji && (range.bullClean || range.bearClean);

  let p1Buy = false;
  let p1Sell = false;
  let p2Buy = false;
  let p2Sell = false;
  let p3Buy = false;
  let p3Sell = false;

  if (idx >= 0 && !isDoji && sessionGate && !masterBlock) {
    const b = m30[idx];

    const e1Bull =
      pineGate &&
      !risk.athZoneBlocked &&
      range.bullClean &&
      immSup != null &&
      okLwk &&
      bullBar &&
      b.l < immSup - zone &&
      b.c > immSup + zone;

    const e1Bear =
      pineGate && range.bearClean && immRes != null && okUwk && bearBar && b.h > immRes + zone && b.c < immRes - zone;

    if (cfg.showHistory || (liveGateBuy && histBullOk)) p1Buy = e1Bull;
    if (cfg.showHistory || (liveGateSell && histBearOk)) p1Sell = e1Bear;

    const e2Bull =
      pineGate &&
      !risk.athZoneBlocked &&
      range.bullClean &&
      !p1Buy &&
      immRes != null &&
      bullBar &&
      b.o > immRes - e2Near &&
      b.c > immRes &&
      okBodyP2 &&
      rLwk > 0.05;

    const e2Bear =
      pineGate &&
      range.bearClean &&
      !p1Sell &&
      immSup != null &&
      bearBar &&
      b.o < immSup + e2Near &&
      b.c < immSup &&
      okBodyP2 &&
      rUwk > 0.05;

    if (cfg.showHistory || (liveGateBuy && histBullOk)) p2Buy = e2Bull;
    if (cfg.showHistory || (liveGateSell && histBearOk)) p2Sell = e2Bear;

    const e3Bull =
      pineGate &&
      !risk.athZoneBlocked &&
      range.bullClean &&
      !p1Buy &&
      !p2Buy &&
      flipSup != null &&
      bullBar &&
      rLwk > 0.2 &&
      b.l <= flipSup + zone * 3 &&
      b.c >= flipSup - zone;

    const e3Bear =
      pineGate &&
      range.bearClean &&
      !p1Sell &&
      !p2Sell &&
      flipRes != null &&
      bearBar &&
      rUwk > 0.2 &&
      b.h >= flipRes - zone * 3 &&
      b.c <= flipRes + zone;

    if (cfg.showHistory || (liveGateBuy && histBullOk)) p3Buy = e3Bull;
    if (cfg.showHistory || (liveGateSell && histBearOk)) p3Sell = e3Bear;
  }

  const sessionOk = inSession || cfg.showHistory;
  const { anyBuy, anySell } = recomputeSignalAggregates(
    { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell },
    {
      sessionOk,
      maxTradesReached,
      newsActive,
      nfpBlackout,
      spreadBlocked,
      dxyBlocksBuy: risk.dxyBlocksBuy,
      athZoneBlocked: risk.athZoneBlocked,
      geoHigh,
    }
  );

  const gates: GateSnapshot = {
    hasStructure,
    structureOk,
    masterBlock,
    sessionGate,
    liveGateBuy,
    liveGateSell,
    hardBlockBuy,
    hardBlockSell,
    maxTradesReached,
  };

  const signals: SignalSnapshot = { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell, anyBuy, anySell };

  return { gates, signals };
}
