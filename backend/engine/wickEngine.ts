import type { Bar, WickMetrics } from './types';

/** Pine f_consolidation_count */
export function consolidationCount(zoneLow: number, zoneHigh: number, bars: Bar[], lookback: number, endExclusive: number): number {
  let count = 0;
  const start = Math.max(1, endExclusive - lookback);
  for (let i = start; i < endExclusive; i++) {
    const b = bars[i];
    const barHi = Math.max(b.o, b.c);
    const barLo = Math.min(b.o, b.c);
    if (barHi <= zoneHigh && barLo >= zoneLow) count += 1;
  }
  return count;
}

/** Pine f_wick_rejection_count */
export function wickRejectionCount(zoneLow: number, zoneHigh: number, bars: Bar[], lookback: number, endExclusive: number): number {
  let count = 0;
  const start = Math.max(1, endExclusive - lookback);
  for (let i = start; i < endExclusive; i++) {
    const b = bars[i];
    const barHi = Math.max(b.o, b.c);
    const barLo = Math.min(b.o, b.c);
    const rng = b.h - b.l;
    const uw = b.h - barHi;
    const lw = barLo - b.l;
    const inZone = b.h >= zoneLow && b.l <= zoneHigh;
    if (inZone && rng > 0 && (uw / rng > 0.6 || lw / rng > 0.6)) count += 1;
  }
  return count;
}

export function wickMetricsAt(bars: Bar[], idx: number): WickMetrics {
  const b = bars[idx];
  const candleRange = b.h - b.l;
  const bodySize = Math.abs(b.c - b.o);
  const upperWick = b.h - Math.max(b.o, b.c);
  const lowerWick = Math.min(b.o, b.c) - b.l;
  const bodyRatio = candleRange > 0 ? bodySize / candleRange : 0;
  const upperWickRatio = candleRange > 0 ? upperWick / candleRange : 0;
  const lowerWickRatio = candleRange > 0 ? lowerWick / candleRange : 0;
  const wickRatio = candleRange > 0 ? Math.max(upperWick, lowerWick) / candleRange : 0;
  const isDoji = bodyRatio < 0.1;
  const isValidBreakout = bodyRatio >= 0.4;
  const isValidRejection = wickRatio >= 0.6;

  const o1 = idx >= 1 ? bars[idx - 1].o : b.o;
  const c1 = idx >= 1 ? bars[idx - 1].c : b.c;
  const jimplasFlipBuy = o1 > c1 && b.c > b.o && lowerWick > 0;
  const jimplasFlipSell = o1 < c1 && b.c < b.o && upperWick > 0;

  return {
    candleRange,
    bodySize,
    upperWick,
    lowerWick,
    bodyRatio,
    wickRatio,
    upperWickRatio,
    lowerWickRatio,
    isDoji,
    isValidBreakout,
    isValidRejection,
    jimplasFlipBuy,
    jimplasFlipSell,
  };
}
