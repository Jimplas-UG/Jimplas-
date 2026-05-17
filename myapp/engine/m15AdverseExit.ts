import type { Bar, BilshenzEngineConfig, TradeJournalRow } from './types';
import { M30_MS } from './m15Bars';

/** SL is on the protective side of the M30 bar before entry (required to arm M15 watch). */
export function slUsesPreviousM30Bar(row: TradeJournalRow, m30: Bar[]): boolean {
  const ei = row.barIndex;
  if (ei < 1 || ei >= m30.length) return false;
  const prev = m30[ei - 1]!;
  if (row.dir === 'BUY') return row.sl <= prev.l;
  return row.sl >= prev.h;
}

/** Exit price at half the distance from entry to full SL. */
export function halfLossExitPrice(row: TradeJournalRow): number {
  if (row.dir === 'BUY') return row.entry - (row.entry - row.sl) * 0.5;
  return row.entry + (row.sl - row.entry) * 0.5;
}

/**
 * Adverse M15 close: candle closed against the position after entry.
 * BUY — bearish close below entry; SELL — bullish close above entry.
 */
export function isAdverseM15Close(row: TradeJournalRow, m15Bar: Bar): boolean {
  if (row.dir === 'BUY') {
    return m15Bar.c < m15Bar.o && m15Bar.c < row.entry;
  }
  return m15Bar.c > m15Bar.o && m15Bar.c > row.entry;
}

/** Fraction of entry→SL risk that price has moved against the position (0–1+). */
export function underwaterRiskFraction(row: TradeJournalRow, price: number): number {
  if (row.dir === 'BUY') {
    const risk = row.entry - row.sl;
    if (!(risk > 0)) return 0;
    const against = row.entry - price;
    return against > 0 ? against / risk : 0;
  }
  const risk = row.sl - row.entry;
  if (!(risk > 0)) return 0;
  const against = price - row.entry;
  return against > 0 ? against / risk : 0;
}

export function armM15ExitWatch(row: TradeJournalRow, m30: Bar[], cfg: BilshenzEngineConfig): TradeJournalRow {
  if (!cfg.enableM15AdverseExit) return row;
  if (!slUsesPreviousM30Bar(row, m30)) return row;
  return {
    ...row,
    m15ExitWatch: true,
    m15CheckedThroughMs: m30[row.barIndex]!.t,
  };
}
