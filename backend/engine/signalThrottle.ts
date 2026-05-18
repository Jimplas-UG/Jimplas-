import type { Bar, BilshenzEngineConfig, SignalSnapshot, TradeJournalRow } from './types';
import { recomputeSignalAggregates } from './signalEngine';

function lastLossBarIndex(journalRows: TradeJournalRow[], currentIdx: number): number | null {
  let best: number | null = null;
  for (const r of journalRows) {
    if (r.out !== 'LOSS' || r.barIndex >= currentIdx) continue;
    if (best === null || r.barIndex > best) best = r.barIndex;
  }
  return best;
}

function lastP3Loss(
  journalRows: TradeJournalRow[],
  currentIdx: number,
  dir: 'BUY' | 'SELL'
): { bar: number; entry: number } | null {
  let bestBar: number | null = null;
  let entry = 0;
  for (const r of journalRows) {
    if (r.out !== 'LOSS' || r.type !== 'P3' || r.dir !== dir || r.barIndex >= currentIdx) continue;
    if (bestBar === null || r.barIndex > bestBar) {
      bestBar = r.barIndex;
      entry = r.entry;
    }
  }
  return bestBar != null ? { bar: bestBar, entry } : null;
}

function rangeExtremes(m30: Bar[], from: number, to: number): { hi: number; lo: number } {
  let hi = -Number.MAX_VALUE;
  let lo = Number.MAX_VALUE;
  for (let i = from; i <= to; i++) {
    if (i < 0 || i >= m30.length) continue;
    hi = Math.max(hi, m30[i].h);
    lo = Math.min(lo, m30[i].l);
  }
  return { hi, lo };
}

/** After P3 BUY loss: price must expand (clear up or sweep down) before another P3 buy. */
function p3BuyRetestOk(
  m30: Bar[],
  idx: number,
  lossBar: number,
  lossEntry: number,
  pip: number,
  waitBars: number,
  sameSideMaxBars: number,
  clearPips: number,
  sweepPips: number
): boolean {
  const since = idx - lossBar;
  if (since < waitBars) return false;
  if (since >= sameSideMaxBars) return true;
  if (clearPips <= 0 && sweepPips <= 0) return true;
  const { hi, lo } = rangeExtremes(m30, lossBar + 1, idx);
  const clearOk = clearPips > 0 && hi >= lossEntry + clearPips * pip;
  const sweepOk = sweepPips > 0 && lo <= lossEntry - sweepPips * pip;
  return clearOk || sweepOk;
}

function p3SellRetestOk(
  m30: Bar[],
  idx: number,
  lossBar: number,
  lossEntry: number,
  pip: number,
  waitBars: number,
  sameSideMaxBars: number,
  clearPips: number,
  sweepPips: number
): boolean {
  const since = idx - lossBar;
  if (since < waitBars) return false;
  if (since >= sameSideMaxBars) return true;
  if (clearPips <= 0 && sweepPips <= 0) return true;
  const { hi, lo } = rangeExtremes(m30, lossBar + 1, idx);
  const clearOk = clearPips > 0 && lo <= lossEntry - clearPips * pip;
  const sweepOk = sweepPips > 0 && hi >= lossEntry + sweepPips * pip;
  return clearOk || sweepOk;
}

function countP3SameSideInLookback(
  journalRows: TradeJournalRow[],
  currentIdx: number,
  lookback: number,
  dir: 'BUY' | 'SELL'
): number {
  const lo = currentIdx - lookback;
  let n = 0;
  for (const r of journalRows) {
    if (r.type !== 'P3' || r.dir !== dir) continue;
    if (r.barIndex >= currentIdx) continue;
    if (r.barIndex >= lo) n += 1;
  }
  return n;
}

/**
 * Cooldown after any loss, cap clustered P3 per side, and require clear/sweep expansion
 * before same-side P3 again after a P3 loss (journal-aware).
 */
export type SignalAggregateDeps = Parameters<typeof recomputeSignalAggregates>[1];

export function applyJournalSignalThrottle(args: {
  cfg: BilshenzEngineConfig;
  m30: Bar[];
  idx: number;
  signals: SignalSnapshot;
  journalRows: TradeJournalRow[];
  aggregateDeps: SignalAggregateDeps;
}): SignalSnapshot {
  const { cfg, m30, idx, journalRows, aggregateDeps } = args;
  let { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell } = args.signals;
  const pip = cfg.pipSize;

  const agg = () =>
    recomputeSignalAggregates({ p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell }, aggregateDeps);

  const lcd = cfg.lossCooldownBars;
  if (lcd > 0) {
    const lastL = lastLossBarIndex(journalRows, idx);
    if (lastL != null && idx - lastL < lcd) {
      p1Buy = p1Sell = p2Buy = p2Sell = p3Buy = p3Sell = false;
      return { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell, ...agg() };
    }
  }

  const lb = cfg.p3LookbackBars;
  const maxP3 = cfg.p3MaxSameSideInLookback;
  if (maxP3 > 0 && lb > 0) {
    if (countP3SameSideInLookback(journalRows, idx, lb, 'BUY') >= maxP3) p3Buy = false;
    if (countP3SameSideInLookback(journalRows, idx, lb, 'SELL') >= maxP3) p3Sell = false;
  }

  const wait = cfg.p3RetestWaitBars;
  const sameMax = cfg.p3SameSideBarsAfterP3Loss;
  const clr = cfg.p3RetestClearPips;
  const swp = cfg.p3RetestSweepPips;

  if (sameMax > 0 || wait > 0 || clr > 0 || swp > 0) {
    const lb3 = lastP3Loss(journalRows, idx, 'BUY');
    if (lb3 != null && p3Buy) {
      if (!p3BuyRetestOk(m30, idx, lb3.bar, lb3.entry, pip, wait, sameMax, clr, swp)) {
        p3Buy = false;
      }
    }
    const ls3 = lastP3Loss(journalRows, idx, 'SELL');
    if (ls3 != null && p3Sell) {
      if (!p3SellRetestOk(m30, idx, ls3.bar, ls3.entry, pip, wait, sameMax, clr, swp)) {
        p3Sell = false;
      }
    }
  }

  return { p1Buy, p1Sell, p2Buy, p2Sell, p3Buy, p3Sell, ...agg() };
}
