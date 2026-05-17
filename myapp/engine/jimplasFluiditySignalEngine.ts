/**
 * Jimplas Market Fluidity — P1 Breakout/Retest, P2 Wick Fill, P3 Session Impulse.
 */
import type { Bar, BiasSnapshot, BilshenzEngineConfig, GateSnapshot, RiskSnapshot, SignalSnapshot } from './types';
import type { SrReplayResult } from './srEngine';
import { nearestResStack, nearestSupStack } from './srEngine';
import type { SessionSnapshot } from './types';
import { consolidationCount, wickMetricsAt } from './wickEngine';
import type { WickMetrics } from './types';
import { recomputeSignalAggregates } from './signalEngine';

export type SetupTradeLevels = {
  setup: 'P1' | 'P2' | 'P3';
  entry: number;
  sl: number;
  tp1: number;
};

function isHighVolume(b: Bar, atrVal: number | null, mult: number): boolean {
  if (atrVal == null || atrVal <= 0) return b.h - b.l > 0;
  const v = b.v ?? 0;
  if (v > 0) return v > 0; // caller compares to avg if needed
  return b.h - b.l >= atrVal * mult;
}

/** Minimal historical chop between entry and target (clean traffic). */
function hasCleanTraffic(
  zoneLow: number,
  zoneHigh: number,
  m30: Bar[],
  idx: number,
  lookback: number,
  maxConsolidation: number
): boolean {
  if (zoneHigh <= zoneLow) return false;
  const c = consolidationCount(zoneLow, zoneHigh, m30, lookback, idx + 1);
  return c <= maxConsolidation;
}

function nextResistanceWithCleanTraffic(
  entry: number,
  sr: SrReplayResult,
  m30: Bar[],
  idx: number,
  pip: number,
  cfg: BilshenzEngineConfig
): number | null {
  const cands = [sr.r1, sr.r2, sr.r3].filter((x): x is number => x != null && x > entry);
  cands.sort((a, b) => a - b);
  for (const tp of cands) {
    if (hasCleanTraffic(entry, tp, m30, idx, cfg.p2CleanTrafficLookback, cfg.p1CleanTrafficMaxChop)) return tp;
  }
  return cands[0] ?? null;
}

function nextSupportWithCleanTraffic(
  entry: number,
  sr: SrReplayResult,
  m30: Bar[],
  idx: number,
  pip: number,
  cfg: BilshenzEngineConfig
): number | null {
  const cands = [sr.s1, sr.s2, sr.s3].filter((x): x is number => x != null && x < entry);
  cands.sort((a, b) => b - a);
  for (const tp of cands) {
    if (hasCleanTraffic(tp, entry, m30, idx, cfg.p2CleanTrafficLookback, cfg.p1CleanTrafficMaxChop)) return tp;
  }
  return cands[0] ?? null;
}

function rangeConsolidationBars(
  level: number,
  zoneHalf: number,
  m30: Bar[],
  endIdx: number,
  lookback: number
): number {
  return consolidationCount(level - zoneHalf, level + zoneHalf, m30, lookback, endIdx + 1);
}

/** Recent H4 range high/low for P3 structure break. */
function h4StructureLevels(h4: Bar[]): { sh: number | null; sl: number | null } {
  const n = h4.length;
  if (n < 2) return { sh: null, sl: null };
  const slice = h4.slice(Math.max(0, n - 4));
  let sh = slice[0]!.h;
  let sl = slice[0]!.l;
  for (const b of slice) {
    if (b.h > sh) sh = b.h;
    if (b.l < sl) sl = b.l;
  }
  return { sh, sl };
}

/** Wick-fill zone from the immediate preceding candle (strategy: break prior bar H/L). */
type WickZone = { lo: number; hi: number; zoneEnd: number; voidPips: number };

/** Loose P2: prior bar wick ratio only (high trade count). */
function wickFillZoneLoose(
  m30: Bar[],
  barIdx: number,
  minWickRatio: number
): { buyZone: WickZone | null; sellZone: WickZone | null } {
  if (barIdx < 0) return { buyZone: null, sellZone: null };
  const b = m30[barIdx]!;
  const w = wickMetricsAt(m30, barIdx);
  const bodyTop = Math.max(b.o, b.c);
  const bodyBot = Math.min(b.o, b.c);
  let buyZone: WickZone | null = null;
  let sellZone: WickZone | null = null;
  if (w.lowerWickRatio >= minWickRatio) {
    const pip = 0.1;
    buyZone = { lo: b.l, hi: bodyTop, zoneEnd: bodyTop, voidPips: (bodyTop - b.l) / pip };
  }
  if (w.upperWickRatio >= minWickRatio) {
    const pip = 0.1;
    sellZone = { lo: bodyBot, hi: b.h, zoneEnd: bodyBot, voidPips: (b.h - bodyBot) / pip };
  }
  return { buyZone, sellZone };
}

function wickFillZoneFromBar(
  m30: Bar[],
  barIdx: number,
  cfg: BilshenzEngineConfig
): { buyZone: WickZone | null; sellZone: WickZone | null } {
  if (!cfg.p2UseStrictFilters) {
    return wickFillZoneLoose(m30, barIdx, cfg.p2WickMinRatio);
  }
  if (barIdx < 0) return { buyZone: null, sellZone: null };
  const b = m30[barIdx]!;
  const w = wickMetricsAt(m30, barIdx);
  const pip = cfg.pipSize;
  const bodyTop = Math.max(b.o, b.c);
  const bodyBot = Math.min(b.o, b.c);
  let buyZone: WickZone | null = null;
  let sellZone: WickZone | null = null;

  const minWickPx = cfg.p2MinWickPips * pip;

  if (
    w.lowerWickRatio >= cfg.p2WickMinRatio &&
    w.bodyRatio <= cfg.p2MaxBodyRatio &&
    w.lowerWick >= minWickPx
  ) {
    const voidPips = (bodyTop - b.l) / pip;
    if (voidPips >= cfg.p2MinVoidPips && voidPips <= cfg.p2MaxVoidPips) {
      buyZone = { lo: b.l, hi: bodyTop, zoneEnd: bodyTop, voidPips };
    }
  }

  if (
    w.upperWickRatio >= cfg.p2WickMinRatio &&
    w.bodyRatio <= cfg.p2MaxBodyRatio &&
    w.upperWick >= minWickPx
  ) {
    const voidPips = (b.h - bodyBot) / pip;
    if (voidPips >= cfg.p2MinVoidPips && voidPips <= cfg.p2MaxVoidPips) {
      sellZone = { lo: bodyBot, hi: b.h, zoneEnd: bodyBot, voidPips };
    }
  }
  return { buyZone, sellZone };
}

function p2VoidHasCleanTraffic(
  zone: WickZone,
  m30: Bar[],
  idx: number,
  cfg: BilshenzEngineConfig
): boolean {
  const chop = consolidationCount(zone.lo, zone.hi, m30, cfg.p2CleanTrafficLookback, idx + 1);
  return chop <= cfg.p2MaxChopInVoid;
}

function p2EntryBarConfirms(
  side: 'BUY' | 'SELL',
  cur: Bar,
  prevBar: Bar,
  wCur: WickMetrics,
  cfg: BilshenzEngineConfig
): boolean {
  const closeBreak =
    side === 'BUY'
      ? !cfg.p2RequireCloseBreak || cur.c > prevBar.h
      : !cfg.p2RequireCloseBreak || cur.c < prevBar.l;
  const wickBreak = side === 'BUY' ? cur.h > prevBar.h : cur.l < prevBar.l;
  const flipOk =
    side === 'BUY'
      ? !cfg.p2RequireFlip || wCur.jimplasFlipBuy
      : !cfg.p2RequireFlip || wCur.jimplasFlipSell;
  const momentumOk = side === 'BUY' ? cur.c > cur.o : cur.c < cur.o;
  return wickBreak && closeBreak && flipOk && momentumOk;
}

function inP3Session(session: SessionSnapshot, cfg: BilshenzEngineConfig): boolean {
  if (cfg.p3LondonOnly && session.london) return true;
  if (cfg.p3NewYorkOnly && session.newYork) return true;
  if (!cfg.p3LondonOnly && !cfg.p3NewYorkOnly) return session.london || session.newYork;
  return false;
}

export function computeGatesAndSignalsJimplasFluidity(args: {
  cfg: BilshenzEngineConfig;
  inSession: boolean;
  session: SessionSnapshot;
  prevInSession: boolean;
  hasStructure: boolean;
  structureOk: boolean;
  dailyTradeCount: number;
  risk: RiskSnapshot;
  bias: BiasSnapshot;
  sr: SrReplayResult;
  m30: Bar[];
  h4: Bar[];
  idx: number;
  atrVal: number | null;
}): { gates: GateSnapshot; signals: SignalSnapshot; levels: SetupTradeLevels | null } {
  const { cfg, inSession, session, prevInSession, hasStructure, structureOk, dailyTradeCount, risk, bias, sr, m30, h4, idx, atrVal } =
    args;

  const pip = cfg.pipSize;
  const slBuf = cfg.journalSlPips * pip;
  const p3Buf = cfg.p3SlBufferPips * pip;
  const zoneHalf = cfg.zoneHalfWidthPips * pip;

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

  let p1Buy = false;
  let p1Sell = false;
  let p2Buy = false;
  let p2Sell = false;
  let p3Buy = false;
  let p3Sell = false;
  let levels: SetupTradeLevels | null = null;

  if (idx >= 2 && sessionGate && !masterBlock) {
    const bo = m30[idx - 1]!;
    const cur = m30[idx]!;
    const prev = m30[idx - 2]!;
    const wBo = wickMetricsAt(m30, idx - 1);
    const prevRes = sr.prevNearestRes ?? nearestResStack(sr.r1, sr.r2, sr.r3, prev.c);
    const prevSup = sr.prevNearestSup ?? nearestSupStack(sr.s1, sr.s2, sr.s3, prev.c);

    // ── P1: S/R breakout + retest (enter on break of breakout candle or next open) ──
    if (cfg.enableP1 && liveGateBuy && prevRes != null) {
      const broke = bo.c > prevRes && bo.o <= prevRes && wBo.bodyRatio >= cfg.p2BodyRatioMin;
      const vol = isHighVolume(bo, atrVal, cfg.p1VolumeAtrMult);
      const consol = rangeConsolidationBars(prevRes, zoneHalf, m30, idx - 1, cfg.p1ConsolidationLookback);
      const inRange = consol >= cfg.p1ConsolidationMinBars && consol <= cfg.p1ConsolidationMaxBars;
      const entryTrigger = cur.h > bo.h || (cur.o > prevRes && bo.c > prevRes);
      if (broke && vol && inRange && entryTrigger) {
        p1Buy = true;
        const entry = cur.c;
        const sl = Math.min(bo.l, prevRes) - slBuf;
        const rawTp =
          nextResistanceWithCleanTraffic(entry, sr, m30, idx, pip, cfg) ??
          nearestResStack(sr.r1, sr.r2, sr.r3, entry);
        let tp1 = rawTp ?? entry + cfg.tp1MinRewardPips * pip;
        const atrCap = atrVal != null && atrVal > 0 ? entry + atrVal * 2.5 : null;
        if (atrCap != null && tp1 > atrCap) tp1 = atrCap;
        levels = { setup: 'P1', entry, sl, tp1 };
      }
    }

    if (cfg.enableP1 && liveGateSell && prevSup != null && !p1Buy) {
      const broke = bo.c < prevSup && bo.o >= prevSup && wBo.bodyRatio >= cfg.p2BodyRatioMin;
      const vol = isHighVolume(bo, atrVal, cfg.p1VolumeAtrMult);
      const consol = rangeConsolidationBars(prevSup, zoneHalf, m30, idx - 1, cfg.p1ConsolidationLookback);
      const inRange = consol >= cfg.p1ConsolidationMinBars && consol <= cfg.p1ConsolidationMaxBars;
      const entryTrigger = cur.l < bo.l || (cur.o < prevSup && bo.c < prevSup);
      if (broke && vol && inRange && entryTrigger) {
        p1Sell = true;
        const entry = cur.c;
        const sl = Math.max(bo.h, prevSup) + slBuf;
        const rawTp =
          nextSupportWithCleanTraffic(entry, sr, m30, idx, pip, cfg) ??
          nearestSupStack(sr.s1, sr.s2, sr.s3, entry);
        let tp1 = rawTp ?? entry - cfg.tp1MinRewardPips * pip;
        const atrCap = atrVal != null && atrVal > 0 ? entry - atrVal * 2.5 : null;
        if (atrCap != null && tp1 < atrCap) tp1 = atrCap;
        levels = { setup: 'P1', entry, sl, tp1 };
      }
    }

    // ── P2: Wick fill — break prior M30 H/L into rejection void ──
    if (cfg.enableP2 && !p1Buy && !p1Sell && !(cfg.p2BlockInChopZone && risk.chopZone)) {
      const prevBar = m30[idx - 1]!;
      const wCur = wickMetricsAt(m30, idx);
      const { buyZone, sellZone } = wickFillZoneFromBar(m30, idx - 1, cfg);
      const nearRes = nearestResStack(sr.r1, sr.r2, sr.r3, cur.c);
      const nearSup = nearestSupStack(sr.s1, sr.s2, sr.s3, cur.c);
      const strict = cfg.p2UseStrictFilters;
      const alignBuy = !strict || !cfg.p2RequireBias || bias.isBullish || (cfg.p2RequireFlip && wCur.jimplasFlipBuy);
      const alignSell = !strict || !cfg.p2RequireBias || bias.isBearish || (cfg.p2RequireFlip && wCur.jimplasFlipSell);

      if (liveGateBuy && buyZone != null && alignBuy) {
        const inZone = cur.l <= buyZone.hi && cur.h >= buyZone.lo;
        const entry = cur.c;
        const voidH = buyZone.zoneEnd - prevBar.l;
        let tp1 = entry + Math.max(voidH, cfg.tp1MinRewardPips * pip);
        if (nearRes != null && nearRes > entry) tp1 = Math.min(tp1, nearRes);
        const sl = prevBar.l - slBuf;
        const clean = !strict || p2VoidHasCleanTraffic(buyZone, m30, idx, cfg);
        const confirmed = !strict || p2EntryBarConfirms('BUY', cur, prevBar, wCur, cfg);
        const trigger = strict ? confirmed : cur.h > prevBar.h;
        if (inZone && trigger && clean && entry > sl && tp1 > entry + pip) {
          p2Buy = true;
          levels = { setup: 'P2', entry, sl, tp1 };
        }
      }

      if (liveGateSell && sellZone != null && !p2Buy && alignSell) {
        const inZone = cur.h >= sellZone.lo && cur.l <= sellZone.hi;
        const entry = cur.c;
        const voidH = prevBar.h - sellZone.zoneEnd;
        let tp1 = entry - Math.max(voidH, cfg.tp1MinRewardPips * pip);
        if (nearSup != null && nearSup < entry) tp1 = Math.max(tp1, nearSup);
        const sl = prevBar.h + slBuf;
        const clean = !strict || p2VoidHasCleanTraffic(sellZone, m30, idx, cfg);
        const confirmed = !strict || p2EntryBarConfirms('SELL', cur, prevBar, wCur, cfg);
        const trigger = strict ? confirmed : cur.l < prevBar.l;
        if (inZone && trigger && clean && sl > entry && tp1 < entry - pip) {
          p2Sell = true;
          levels = { setup: 'P2', entry, sl, tp1 };
        }
      }
    }

    // ── P3: Session open impulse (London / NY only) ──
    if (cfg.enableP3 && !p1Buy && !p1Sell && !p2Buy && !p2Sell) {
      const p3Sess = inP3Session(session, cfg);
      const sessionJustOpened = p3Sess && inSession && !prevInSession;
      const wCur = wickMetricsAt(m30, idx);
      const { sh, sl: sLo } = h4StructureLevels(h4);

      if (sessionJustOpened && p3Sess) {
        if (liveGateBuy && bias.isBullish && wCur.jimplasFlipBuy && sh != null && cur.h > sh) {
          p3Buy = true;
          const entry = cur.c;
          const sl = cur.l - p3Buf;
          const tp1 = entry + (entry - sl) * cfg.p3RewardRisk;
          levels = { setup: 'P3', entry, sl, tp1 };
        } else if (liveGateSell && bias.isBearish && wCur.jimplasFlipSell && sLo != null && cur.l < sLo) {
          p3Sell = true;
          const entry = cur.c;
          const sl = cur.h + p3Buf;
          const tp1 = entry - (sl - entry) * cfg.p3RewardRisk;
          levels = { setup: 'P3', entry, sl, tp1 };
        }
      }
    }
  }

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
    levels,
  };
}
