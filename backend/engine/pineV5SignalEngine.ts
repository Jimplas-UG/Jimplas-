import type { Bar, BiasSnapshot, BilshenzEngineConfig, GateSnapshot, RangeCleanSnapshot, RiskSnapshot, SignalSnapshot } from './types';
import type { SrReplayResult } from './srEngine';
import { consolidationCount, wickMetricsAt, wickRejectionCount } from './wickEngine';
import { recomputeSignalAggregates } from './signalEngine';

/** Pine f_consolidation_count + f_wick_rejection_count left-side clean. */
export function leftSideScanPineV5(args: {
  nearestRes: number | null;
  nearestSup: number | null;
  close: number;
  pip: number;
  m30: Bar[];
  idx: number;
  minPips: number;
}): RangeCleanSnapshot {
  const { nearestRes, nearestSup, close, pip, m30, idx, minPips } = args;
  const distRes = nearestRes != null ? (nearestRes - close) / pip : 0;
  const distSup = nearestSup != null ? (close - nearestSup) / pip : 0;
  const bullRangeOk = nearestRes != null && distRes >= minPips;
  const bearRangeOk = nearestSup != null && distSup >= minPips;

  let bullClean = false;
  if (nearestRes != null && bullRangeOk && idx >= 1) {
    const consolZone = 15 * pip;
    const cb = consolidationCount(close, close + consolZone, m30, 20, idx + 1);
    const wb = wickRejectionCount(close, nearestRes, m30, 30, idx + 1);
    bullClean = cb <= 5 && wb <= 3;
  }

  let bearClean = false;
  if (nearestSup != null && bearRangeOk && idx >= 1) {
    const consolZone = 15 * pip;
    const cs = consolidationCount(close - consolZone, close, m30, 20, idx + 1);
    const ws = wickRejectionCount(nearestSup, close, m30, 30, idx + 1);
    bearClean = cs <= 5 && ws <= 3;
  }

  return {
    bullPips: distRes,
    bearPips: distSup,
    bullRangeOk,
    bearRangeOk,
    bullClean,
    bearClean,
    bullChop: 0,
    bearChop: 0,
  };
}

function brokenBelow(m30: Bar[], idx: number, level: number, lookback: number): boolean {
  for (let i = 1; i <= lookback; i++) {
    const j = idx - i;
    if (j < 0) break;
    if (m30[j].c < level) return true;
  }
  return false;
}

function brokenAbove(m30: Bar[], idx: number, level: number, lookback: number): boolean {
  for (let i = 1; i <= lookback; i++) {
    const j = idx - i;
    if (j < 0) break;
    if (m30[j].c > level) return true;
  }
  return false;
}

/**
 * Original TradingView Pine v5 entry logic (P1 wick / P2 breakout / P3 flip).
 * Matches user script: pivot 3/3, max 3 trades/day, show_history relaxes clean-range on signals.
 */
export function computeGatesAndSignalsPineV5(args: {
  cfg: BilshenzEngineConfig;
  inSession: boolean;
  hasStructure: boolean;
  structureOk: boolean;
  dailyTradeCount: number;
  risk: RiskSnapshot;
  bias: BiasSnapshot;
  sr: SrReplayResult;
  range: RangeCleanSnapshot;
  m30: Bar[];
  idx: number;
}): { gates: GateSnapshot; signals: SignalSnapshot } {
  const { cfg, inSession, hasStructure, structureOk, dailyTradeCount, risk, bias, sr, range, m30, idx } = args;

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

  let p1Buy = false;
  let p1Sell = false;
  let p2Buy = false;
  let p2Sell = false;
  let p3Buy = false;
  let p3Sell = false;

  if (idx >= 1) {
    const wick = wickMetricsAt(m30, idx);
    const isDoji = wick.isDoji;
    const b = m30[idx];
    const prevRes = sr.prevNearestRes;
    const prevSup = sr.prevNearestSup;

    if (!isDoji && sessionGate && !masterBlock) {
      // ── P1 Wick ──
      if (prevSup != null && (cfg.showHistory || (liveGateBuy && range.bullRangeOk && histBullOk))) {
        const sweptBelow = m30[idx - 1].l < prevSup || b.l < prevSup;
        const closedAbove = b.c > prevSup;
        const hasLowWick = wick.wickRatio >= 0.6 && wick.lowerWick >= wick.upperWick;
        const biasOkBuy = !bias.isBearish;
        const jimplasOkBuy = wick.jimplasFlipBuy || (!wick.jimplasFlipBuy && !wick.jimplasFlipSell);
        if (sweptBelow && closedAbove && hasLowWick && biasOkBuy && jimplasOkBuy) p1Buy = true;
      }

      if (prevRes != null && (cfg.showHistory || (liveGateSell && range.bearRangeOk && histBearOk))) {
        const sweptAbove = m30[idx - 1].h > prevRes || b.h > prevRes;
        const closedBelow = b.c < prevRes;
        const hasUpWick = wick.wickRatio >= 0.6 && wick.upperWick >= wick.lowerWick;
        const biasOkSell = !bias.isBullish;
        const jimplasOkSell = wick.jimplasFlipSell || (!wick.jimplasFlipBuy && !wick.jimplasFlipSell);
        if (sweptAbove && closedBelow && hasUpWick && biasOkSell && jimplasOkSell) p1Sell = true;
      }

      // ── P2 Breakout ──
      if (!risk.chopZone && !p1Buy && !p1Sell) {
        if (prevRes != null && (cfg.showHistory || (liveGateBuy && range.bullRangeOk && histBullOk))) {
          const brokeUp = b.c > prevRes && b.o <= prevRes;
          const hasBody = wick.bodyRatio >= 0.4;
          const hasLowWick = wick.lowerWick >= wick.candleRange * 0.1;
          if (brokeUp && hasBody && hasLowWick && bias.isBullish) p2Buy = true;
        }
        if (prevSup != null && (cfg.showHistory || (liveGateSell && range.bearRangeOk && histBearOk))) {
          const brokeDown = b.c < prevSup && b.o >= prevSup;
          const hasBody = wick.bodyRatio >= 0.4;
          const hasUpWick = wick.upperWick >= wick.candleRange * 0.1;
          if (brokeDown && hasBody && hasUpWick && bias.isBearish) p2Sell = true;
        }
      }

      // ── P3 Flip (optional — disabled when cfg.enableP3 is false) ──
      if (cfg.enableP3 && !risk.chopZone && !p1Buy && !p1Sell && !p2Buy && !p2Sell) {
        const supBroken = prevSup != null && brokenBelow(m30, idx, prevSup, 10);
        const resBroken = prevRes != null && brokenAbove(m30, idx, prevRes, 10);

        if (prevSup != null && supBroken && (cfg.showHistory || (liveGateBuy && range.bullRangeOk && histBullOk))) {
          const touched = b.h >= prevSup;
          const rejected = b.c < prevSup;
          const upperWickPct = wick.candleRange > 0 ? wick.upperWick / wick.candleRange : 0;
          if (touched && rejected && upperWickPct >= 0.6 && !bias.isBearish) p3Buy = true;
        }

        if (prevRes != null && resBroken && (cfg.showHistory || (liveGateSell && range.bearRangeOk && histBearOk))) {
          const touched = b.l <= prevRes;
          const rejected = b.c > prevRes;
          const lowerWickPct = wick.candleRange > 0 ? wick.lowerWick / wick.candleRange : 0;
          if (touched && rejected && lowerWickPct >= 0.6 && !bias.isBullish) p3Sell = true;
        }
      }
    }
  }

  // Pine any_buy / any_sell require in_session (show_history does not bypass this).
  const { anyBuy, anySell } = recomputeSignalAggregates(
    { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell },
    {
      sessionOk: inSession,
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

  return {
    gates,
    signals: { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell, anyBuy, anySell },
  };
}
