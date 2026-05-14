import { ema, highs, lows, lastFinite, pivotHighConfirmAt, pivotLowConfirmAt } from './indicators';
import type { Bar, BiasSnapshot } from './types';

/**
 * Pine v3.2 Section 3 — EMA50 on chart TF (M30) + pivot 5,5 HH/HL vs LH/LL.
 * `ema50H4` field carries M30 EMA50 for existing UI that reads ema50H4.
 */
export function computeBias(_h4: Bar[], d1: Bar[], chartClose: number, m30?: Bar[]): BiasSnapshot {
  const n = d1.length;
  let dHigh0: number | null = null;
  let dHigh1: number | null = null;
  let dLow0: number | null = null;
  let dLow1: number | null = null;
  if (n >= 2) {
    dHigh0 = d1[n - 1].h;
    dLow0 = d1[n - 1].l;
    dHigh1 = d1[n - 2].h;
    dLow1 = d1[n - 2].l;
  }

  const Ls = 5;
  const Rs = 5;
  let ema50M30: number | null = null;
  let ema21M30: number | null = null;
  let lastPh: number | null = null;
  let lastPl: number | null = null;
  let prevPh: number | null = null;
  let prevPl: number | null = null;

  if (m30 && m30.length >= 50) {
    const m30c = m30.map((b) => b.c);
    ema50M30 = lastFinite(ema(m30c, 50));
    if (m30.length >= 21) ema21M30 = lastFinite(ema(m30c, 21));

    const HH = highs(m30);
    const LL = lows(m30);
    const start = Ls + Rs;
    for (let conf = start; conf < m30.length; conf++) {
      const ph = pivotHighConfirmAt(HH, conf, Ls, Rs);
      if (ph != null) {
        prevPh = lastPh;
        lastPh = ph;
      }
      const pl = pivotLowConfirmAt(LL, conf, Ls, Rs);
      if (pl != null) {
        prevPl = lastPl;
        lastPl = pl;
      }
    }
  }

  const hhHl =
    lastPh != null &&
    prevPh != null &&
    lastPh > prevPh &&
    lastPl != null &&
    prevPl != null &&
    lastPl > prevPl;
  const lhLl =
    lastPh != null &&
    prevPh != null &&
    lastPh < prevPh &&
    lastPl != null &&
    prevPl != null &&
    lastPl < prevPl;

  const aboveEma = ema50M30 != null && chartClose > ema50M30;
  const isBullish = !!(ema50M30 != null && aboveEma && hhHl);
  const isBearish = !!(ema50M30 != null && !aboveEma && lhLl);

  const bullStructure = hhHl;
  const bearStructure = lhLl;

  return {
    ema50H4: ema50M30,
    ema21M30,
    dHigh0,
    dHigh1,
    dLow0,
    dLow1,
    bullStructure,
    bearStructure,
    isBullish,
    isBearish,
  };
}
