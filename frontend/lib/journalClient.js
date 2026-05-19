/** Journal row helpers for the mobile client (strategy snapshot comes from desk-api). */

import { armM15ExitWatch, applyM15AdverseExit } from './m15AdverseExit';

export function resolveJournalOnBar(rows, bar, barIndex, ctx) {
  return rows.map((row) => {
    if (row.out !== 'OPEN' || row.tp1 == null || !Number.isFinite(row.tp1)) return row;
    if (barIndex <= row.barIndex) return row;

    let r = row;
    if (ctx?.cfg?.enableM15AdverseExit && ctx.m15?.length > 0 && ctx.m30?.length > 0) {
      r = applyM15AdverseExit(r, ctx.m15, ctx.m30, barIndex, ctx.cfg);
      if (r.out !== 'OPEN') return r;
    }

    if (r.dir === 'BUY') {
      if (bar.l <= r.sl) return { ...r, out: 'LOSS' };
      if (r.tp1 != null && bar.h >= r.tp1) return { ...r, out: 'WIN' };
    } else {
      if (bar.h >= r.sl) return { ...r, out: 'LOSS' };
      if (r.tp1 != null && bar.l <= r.tp1) return { ...r, out: 'WIN' };
    }
    return r;
  });
}

export function buildManualJournalEntry({ trade, barIndex, timeStr, m30, cfg }) {
  const t = trade;
  if (!t?.side || t.entry == null || !Number.isFinite(t.entry) || t.sl == null || !Number.isFinite(t.sl)) {
    return null;
  }
  if (t.tp1 == null || !Number.isFinite(t.tp1)) return null;
  const typ = t.setup === 'P2' ? 'P2' : t.setup === 'P3' ? 'P3' : 'P1';
  let row = {
    entry: t.entry,
    sl: t.sl,
    tp1: t.tp1,
    dir: t.side,
    type: typ,
    time: timeStr,
    out: 'OPEN',
    barIndex,
  };
  if (cfg && m30?.length) {
    row = armM15ExitWatch(row, m30, cfg);
  }
  return row;
}
