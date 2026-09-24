/**
 * Live USDT-M linear floating PnL from mark vs entry (keeps UI updating while REST cools).
 */

export function legSideOf(pos) {
  return String(
    pos?.positionSide || pos?.leg || (pos?.type === 'SELL' ? 'SHORT' : 'LONG'),
  ).toUpperCase();
}

/** Approximate unrealized PnL for one linear futures leg. */
export function liveLegProfit(pos, markPrice) {
  const mark = Number(markPrice);
  const entry = Number(pos?.price_open ?? pos?.entryPrice ?? 0);
  const vol = Number(pos?.volume ?? pos?.qty ?? 0);
  if (!(mark > 0) || !(entry > 0) || !(vol > 0)) {
    const sticky = Number(pos?.profit ?? 0);
    return Number.isFinite(sticky) ? sticky : 0;
  }
  const side = legSideOf(pos);
  const short = side === 'SHORT' || side === 'SELL' || pos?.type === 'SELL';
  return short ? (entry - mark) * vol : (mark - entry) * vol;
}

/**
 * @param {object[]} positions
 * @param {Record<string, number>|number|null} marks — map by symbol, or single mark for one symbol
 * @param {string|null} quoteSymbol — when marks is a number, only apply to this symbol
 */
export function liveFloatingTotal(positions, marks, quoteSymbol = null) {
  const rows = Array.isArray(positions) ? positions : [];
  if (!rows.length) return 0;
  const q = quoteSymbol ? String(quoteSymbol).toUpperCase() : null;
  const single = typeof marks === 'number' ? marks : null;
  const map = marks && typeof marks === 'object' ? marks : null;
  return rows.reduce((sum, p) => {
    const sym = String(p?.symbol || '').toUpperCase();
    let mark = null;
    if (map && Number(map[sym]) > 0) mark = Number(map[sym]);
    else if (single != null && Number.isFinite(single) && (!q || sym === q)) mark = single;
    return sum + liveLegProfit(p, mark);
  }, 0);
}

/** Prefer account with real balances over a cool-path stub. */
export function mergeStickyAccount(prev, next) {
  if (!next) return prev ?? null;
  const nextHas =
    next.balance != null || next.equity != null || (next.profit != null && !next.stale);
  const prevHas = prev && (prev.balance != null || prev.equity != null || prev.profit != null);
  if (!nextHas && prevHas) {
    return {
      ...prev,
      stale: true,
      warning: next.warning || prev.warning,
    };
  }
  if (next.stale && prevHas && next.balance == null && next.equity == null) {
    return {
      ...prev,
      stale: true,
      warning: next.warning || prev.warning,
      profit: next.profit != null ? next.profit : prev.profit,
    };
  }
  return next;
}
