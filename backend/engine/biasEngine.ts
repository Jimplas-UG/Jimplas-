import { ema, lastFinite } from './indicators';
import type { Bar, BiasSnapshot } from './types';

/**
 * Pine HTF bias — EMA50 on H4 + daily HH/HL vs LH/LL structure.
 * is_bullish = close > ema50_h4 and bull_structure
 * is_bearish = close < ema50_h4 and bear_structure
 */
export function computeBias(h4: Bar[], d1: Bar[], chartClose: number, m30?: Bar[]): BiasSnapshot {
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

  const bullStructure = !!(dHigh0 != null && dHigh1 != null && dLow0 != null && dLow1 != null && dHigh0 > dHigh1 && dLow0 > dLow1);
  const bearStructure = !!(dHigh0 != null && dHigh1 != null && dLow0 != null && dLow1 != null && dHigh0 < dHigh1 && dLow0 < dLow1);

  let ema50H4: number | null = null;
  let ema21M30: number | null = null;
  if (h4.length >= 50) {
    const h4c = h4.map((b) => b.c);
    ema50H4 = lastFinite(ema(h4c, 50));
  }
  if (m30 && m30.length >= 21) {
    const m30c = m30.map((b) => b.c);
    ema21M30 = lastFinite(ema(m30c, 21));
  }

  const isBullish = ema50H4 != null && chartClose > ema50H4 && bullStructure;
  const isBearish = ema50H4 != null && chartClose < ema50H4 && bearStructure;

  return {
    ema50H4,
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
