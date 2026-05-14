import type { BilshenzEngineConfig } from './types';

/** Reward / risk in price units (TP distance ÷ SL distance). Null if geometry invalid. */
export function rewardRiskRatio(entry: number, sl: number, tp1: number, side: 'BUY' | 'SELL'): number | null {
  const riskD = side === 'BUY' ? entry - sl : sl - entry;
  const rewD = side === 'BUY' ? tp1 - entry : entry - tp1;
  if (!(riskD > 0) || !(rewD > 0) || !Number.isFinite(riskD) || !Number.isFinite(rewD)) return null;
  return rewD / riskD;
}

/**
 * Forces TP1 on the correct side of entry and clamps reward distance (tighter max → higher TP1 hit rate
 * at the cost of smaller wins — typical weakness was full-structure TP with SL hit first).
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
