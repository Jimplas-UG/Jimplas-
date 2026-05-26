/** Maps journal row → HistRow tuple shape used in App.js */
export function mapJournalRowToHist(row) {
  const typ = row.type === 'P1' ? 'P1' : row.type === 'P2' ? 'P2' : row.type === 'P3' ? 'P3' : 'P2';
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

export function mapJournalToHistRows(rows) {
  return (rows ?? []).map(mapJournalRowToHist);
}

/**
 * Map raw MT5 deals (from /api/logs) into the HistRow tuple format.
 * Filters to actual trades (type 0=BUY / 1=SELL with a symbol),
 * pairs entry+exit by position_id/order, and shows closed P&L.
 */
export function mapMt5DealsToHistRows(deals) {
  if (!Array.isArray(deals) || !deals.length) return [];
  const tradeDealsSorted = deals
    .filter((d) => (d.type === 0 || d.type === 1) && d.symbol)
    .sort((a, b) => b.time - a.time);

  return tradeDealsSorted.map((d) => {
    const dt = new Date(d.time * 1000);
    const hh = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    const timeStr = `${hh}:${mm}`;
    const isBuy = d.type === 0;
    const dir = isBuy ? '▲' : '▼';
    const side = isBuy ? 'buy' : 'sell';
    const priceStr = d.price > 0 ? d.price.toFixed(2) : '—';
    const volStr = `${d.volume} lot`;
    const profit = d.profit;
    const isEntry = profit === 0;
    let resultStr, outcome, kind;
    if (isEntry) {
      resultStr = 'Pending';
      outcome = 'OPEN';
      kind = 'open';
    } else if (profit > 0) {
      resultStr = `+$${profit.toFixed(2)}`;
      outcome = 'WIN';
      kind = 'win';
    } else {
      resultStr = `-$${Math.abs(profit).toFixed(2)}`;
      outcome = 'SL HIT';
      kind = 'loss';
    }
    return [timeStr, dir, 'MT5', priceStr, volStr, d.symbol, resultStr, outcome, side, kind];
  });
}

/** Sum daily P&L from MT5 deals (type 0/1 only, today's date). */
export function mt5DealsDailyPnl(deals) {
  if (!Array.isArray(deals) || !deals.length) return 0;
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  let total = 0;
  for (const d of deals) {
    if ((d.type !== 0 && d.type !== 1) || !d.symbol) continue;
    if (d.time < todayStart) continue;
    total += d.profit;
  }
  return total;
}

/** Total P&L from all MT5 deals (type 0/1 with symbol). */
export function mt5DealsTotalPnl(deals) {
  if (!Array.isArray(deals) || !deals.length) return 0;
  let total = 0;
  for (const d of deals) {
    if ((d.type !== 0 && d.type !== 1) || !d.symbol) continue;
    total += d.profit;
  }
  return total;
}
