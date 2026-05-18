/** Journal row helpers for the mobile client (strategy snapshot comes from desk-api). */

export function resolveJournalOnBar(rows, bar, barIndex) {
  return rows.map((row) => {
    if (row.out !== 'OPEN' || row.tp1 == null || !Number.isFinite(row.tp1)) return row;
    if (barIndex <= row.barIndex) return row;
    if (row.dir === 'BUY') {
      if (bar.l <= row.sl) return { ...row, out: 'LOSS' };
      if (row.tp1 != null && bar.h >= row.tp1) return { ...row, out: 'WIN' };
    } else {
      if (bar.h >= row.sl) return { ...row, out: 'LOSS' };
      if (row.tp1 != null && bar.l <= row.tp1) return { ...row, out: 'WIN' };
    }
    return row;
  });
}

export function buildManualJournalEntry({ trade, barIndex, timeStr }) {
  const t = trade;
  if (!t?.side || t.entry == null || !Number.isFinite(t.entry) || t.sl == null || !Number.isFinite(t.sl)) {
    return null;
  }
  if (t.tp1 == null || !Number.isFinite(t.tp1)) return null;
  const typ = t.setup === 'P2' ? 'P2' : t.setup === 'P3' ? 'P3' : 'P1';
  return {
    entry: t.entry,
    sl: t.sl,
    tp1: t.tp1,
    dir: t.side,
    type: typ,
    time: timeStr,
    out: 'OPEN',
    barIndex,
  };
}
