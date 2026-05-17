import type { BilshenzEngineConfig } from './types';

/** Reward / risk in price units (TP distance ÷ SL distance). Null if geometry invalid. */
export function rewardRiskRatio(entry: number, sl: number, tp1: number, side: 'BUY' | 'SELL'): number | null {
  const riskD = side === 'BUY' ? entry - sl : sl - entry;
  const rewD = side === 'BUY' ? tp1 - entry : entry - tp1;
  if (!(riskD > 0) || !(rewD > 0) || !Number.isFinite(riskD) || !Number.isFinite(rewD)) return null;
  return rewD / riskD;
}

/**
 * Legacy global TP clamp (10–28 pips). Used only when Jimplas per-setup geometry is off.
 */
export function clampTp1ForJournal(
  side: 'BUY' | 'SELL',
  entry: number,
  sl: number,
  rawTp1: number | null,
  cfg: BilshenzEngineConfig
): number | null {
  if (rawTp1 == null || !Number.isFinite(rawTp1) || !Number.isFinite(entry) || !Number.isFinite(sl)) return null;
  const pip = cfg.pipSize;
  const minRp = Math.max(1, cfg.tp1MinRewardPips) * pip;
  const maxRp = Math.max(minRp, cfg.tp1MaxRewardPips) * pip;

  if (side === 'BUY') {
    const riskD = entry - sl;
    if (!(riskD > 0)) return null;
    let tp = rawTp1;
    if (tp <= entry) tp = entry + minRp;
    let rew = tp - entry;
    if (rew < minRp) tp = entry + minRp;
    else if (rew > maxRp) tp = entry + maxRp;
    return tp;
  }
  const riskD = sl - entry;
  if (!(riskD > 0)) return null;
  let tp = rawTp1;
  if (tp >= entry) tp = entry - minRp;
  let rew = entry - tp;
  if (rew < minRp) tp = entry - minRp;
  else if (rew > maxRp) tp = entry - maxRp;
  return tp;
}

function capSlDistance(
  side: 'BUY' | 'SELL',
  entry: number,
  sl: number,
  maxSlPips: number,
  pip: number
): number {
  if (!(maxSlPips > 0)) return sl;
  const maxD = maxSlPips * pip;
  if (side === 'BUY') {
    const minSl = entry - maxD;
    return sl < minSl ? minSl : sl;
  }
  const maxSl = entry + maxD;
  return sl > maxSl ? maxSl : sl;
}

/**
 * High-volume mode: keep natural (wide) SL, set TP from SL distance so wins scale with risk.
 * Does not tighten SL (preserves ~60% hit profile on TP before distant SL).
 */
export function applyBalancedClampGeometry(
  side: 'BUY' | 'SELL',
  entry: number,
  sl: number,
  rawTp1: number | null,
  _setup: 'P1' | 'P2' | 'P3',
  cfg: BilshenzEngineConfig
): { sl: number; tp1: number | null } {
  const pip = cfg.pipSize;
  const sSl = sl;

  const riskD = side === 'BUY' ? entry - sSl : sSl - entry;
  if (!(riskD > 0)) return { sl: sSl, tp1: null };

  const riskPips = riskD / pip;
  const minFloor = Math.max(1, cfg.tp1MinRewardPips);
  const maxCap = Math.max(minFloor, cfg.tp1MaxRewardPips);
  const frac = Math.max(0.4, Math.min(1, cfg.tpClampSlFraction));
  const rrFloor = Math.max(frac, cfg.tpClampMinRiskReward > 0 ? Math.min(frac, cfg.tpClampMinRiskReward) : frac);
  let targetPips = riskPips * rrFloor;
  targetPips = Math.min(maxCap, Math.max(minFloor, targetPips));

  const targetRew = targetPips * pip;

  if (side === 'BUY') {
    let tp = entry + targetRew;
    if (rawTp1 != null && rawTp1 > entry) {
      const rawPips = (rawTp1 - entry) / pip;
      if (rawPips >= minFloor && rawPips <= maxCap) tp = rawTp1;
    }
    return { sl: sSl, tp1: tp };
  }
  let tp = entry - targetRew;
  if (rawTp1 != null && rawTp1 < entry) {
    const rawPips = (entry - rawTp1) / pip;
    if (rawPips >= minFloor && rawPips <= maxCap) tp = rawTp1;
  }
  return { sl: sSl, tp1: tp };
}

/** Reject entries whose stop is unreasonably wide for the TP clamp model. */
export function slPipsFromEntry(side: 'BUY' | 'SELL', entry: number, sl: number, pip: number): number {
  return side === 'BUY' ? (entry - sl) / pip : (sl - entry) / pip;
}

/** SL distance for $ risk / lots when structural stop is wider than the journal risk model. */
export function resolveJournalSizingSlPips(structuralSlPips: number, cfg: BilshenzEngineConfig): number {
  if (cfg.journalSizingSlPips > 0) return cfg.journalSizingSlPips;
  return structuralSlPips;
}

/**
 * When SL is much wider than TP cap, size positions smaller so a win pays ~same R as a loss.
 * Preserves wide structural SL (high WR) without oversized losses on stop-outs.
 */
export function riskScaleForSlTpMismatch(slPips: number, cfg: BilshenzEngineConfig): number {
  if (!cfg.riskScaleWideStops || cfg.tp1MaxRewardPips <= 0) return 1;
  const ratio = cfg.tp1MaxRewardPips / Math.max(slPips, 0.1);
  return Math.min(1, Math.max(0.15, ratio));
}

/**
 * Jimplas Fluidity per-setup SL/TP — matches strategy instructions (no global 10–28 pip TP cap).
 */
export function finalizeJimplasTradeGeometry(
  setup: 'P1' | 'P2' | 'P3',
  side: 'BUY' | 'SELL',
  entry: number,
  sl: number,
  rawTp: number,
  cfg: BilshenzEngineConfig
): { sl: number; tp1: number; rr: number | null } {
  const pip = cfg.pipSize;
  const minFloor = Math.max(1, cfg.tp1MinRewardPips) * pip;

  if (side === 'BUY') {
    let sSl = sl;
    if (setup === 'P1' && cfg.p1MaxSlPips > 0) sSl = capSlDistance('BUY', entry, sSl, cfg.p1MaxSlPips, pip);
    if (setup === 'P2' && cfg.p2MaxSlPips > 0) sSl = capSlDistance('BUY', entry, sSl, cfg.p2MaxSlPips, pip);

    let riskD = entry - sSl;
    if (!(riskD > 0)) {
      sSl = entry - minFloor;
      riskD = minFloor;
    }

    let tp = rawTp;
    if (setup === 'P3') {
      tp = entry + riskD * cfg.p3RewardRisk;
    } else if (setup === 'P2') {
      const capped = clampTp1ForJournal('BUY', entry, sSl, tp, cfg);
      tp = capped ?? entry + minFloor;
    } else {
      const minRR = cfg.p1MinRewardRisk;
      const maxRew = cfg.p1MaxTpPips > 0 ? cfg.p1MaxTpPips * pip : Number.POSITIVE_INFINITY;
      const minRew = Math.min(Math.max(minFloor, riskD * minRR), maxRew);
      if (tp <= entry) tp = entry + minRew;
      let rew = tp - entry;
      if (rew < minRew) tp = entry + minRew;
      if (rew > maxRew) tp = entry + maxRew;
    }

    return { sl: sSl, tp1: tp, rr: rewardRiskRatio(entry, sSl, tp, 'BUY') };
  }

  let sSl = sl;
  if (setup === 'P1' && cfg.p1MaxSlPips > 0) sSl = capSlDistance('SELL', entry, sSl, cfg.p1MaxSlPips, pip);
  if (setup === 'P2' && cfg.p2MaxSlPips > 0) sSl = capSlDistance('SELL', entry, sSl, cfg.p2MaxSlPips, pip);

  let riskD = sSl - entry;
  if (!(riskD > 0)) {
    sSl = entry + minFloor;
    riskD = minFloor;
  }

  let tp = rawTp;
  if (setup === 'P3') {
    tp = entry - riskD * cfg.p3RewardRisk;
  } else if (setup === 'P2') {
    const capped = clampTp1ForJournal('SELL', entry, sSl, tp, cfg);
    tp = capped ?? entry - minFloor;
  } else {
    const minRR = cfg.p1MinRewardRisk;
    const maxRew = cfg.p1MaxTpPips > 0 ? cfg.p1MaxTpPips * pip : Number.POSITIVE_INFINITY;
    const minRew = Math.min(Math.max(minFloor, riskD * minRR), maxRew);
    if (tp >= entry) tp = entry - minRew;
    let rew = entry - tp;
    if (rew < minRew) tp = entry - minRew;
    if (rew > maxRew) tp = entry + maxRew;
  }

  return { sl: sSl, tp1: tp, rr: rewardRiskRatio(entry, sSl, tp, 'SELL') };
}
