import type { TradeJournalRow } from './types';

/** Maps engine journal row → `HistRow` tuple shape used in App.js */
export function mapJournalRowToHist(row: TradeJournalRow): (string | number)[] {
  const typ = row.type === 'P1' ? 'WICK' : row.type === 'P2' ? 'BREAK' : 'FLIP';
  const dir = row.dir === 'BUY' ? '▲' : '▼';
  const side = row.dir === 'BUY' ? 'buy' : 'sell';
  const e1 = row.entry.toFixed(2);
  const e2 = row.sl.toFixed(2);
  const e3 = row.tp1 != null && Number.isFinite(row.tp1) ? row.tp1.toFixed(2) : '—';
  const e4 = row.out === 'OPEN' ? 'Pending' : row.out === 'WIN' ? '✓ TP1' : '✗ SL';
  const res = row.out === 'WIN' ? 'WIN' : row.out === 'LOSS' ? 'SL HIT' : 'OPEN';
  const kind = row.out === 'WIN' ? 'win' : row.out === 'LOSS' ? 'loss' : 'open';
  return [row.time, dir, typ, e1, e2, e3, e4, res, side, kind];
}

export function mapJournalToHistRows(rows: TradeJournalRow[]): (string | number)[][] {
  return rows.map(mapJournalRowToHist);
}
