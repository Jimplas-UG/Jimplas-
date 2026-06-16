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

export const HIST_RANGE_OPTIONS = [
  { id: 'today', badge: 'TODAY', label: 'Today' },
  { id: 'week', badge: 'WEEKLY', label: 'Weekly' },
  { id: '30d', badge: '30 DAYS', label: '30 Days' },
];

/** UTC start of calendar day, or rolling window for week / 30d. */
export function histRangeCutoffMs(rangeKey, nowMs = Date.now()) {
  const d = new Date(nowMs);
  if (rangeKey === 'week') return nowMs - 7 * 24 * 3600 * 1000;
  if (rangeKey === '30d') return nowMs - 30 * 24 * 3600 * 1000;
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

export function filterJournalRowsByRange(rows, m30, rangeKey, nowMs = Date.now()) {
  const cutoff = histRangeCutoffMs(rangeKey, nowMs);
  return (rows ?? []).filter((row) => {
    const bi = row.barIndex;
    const barT = m30?.[bi]?.t;
    if (barT != null && Number.isFinite(barT)) return barT >= cutoff;
    return rangeKey === 'today';
  });
}

export function filterBinanceDealsByRange(deals, rangeKey, nowMs = Date.now()) {
  const cutoffMs = histRangeCutoffMs(rangeKey, nowMs);
  return (deals ?? []).filter((d) => (d.time ?? 0) >= cutoffMs);
}

export function isBinanceDealRow(d) {
  return d && (d.type === 'BUY' || d.type === 'SELL');
}

/** Map Binance userTrades (/api/logs) into HistRow tuples. */
export function mapBinanceDealsToHistRows(deals) {
  if (!Array.isArray(deals) || !deals.length) return [];
  const sorted = [...deals].sort((a, b) => (b.time ?? 0) - (a.time ?? 0));
  return sorted.map((d) => {
    const t = d.time ?? 0;
    const dt = new Date(t);
    const hh = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    const timeStr = `${hh}:${mm}`;
    const isBuy = d.type === 'BUY';
    const dir = isBuy ? '▲' : '▼';
    const side = isBuy ? 'buy' : 'sell';
    const priceStr = d.price > 0 ? Number(d.price).toFixed(2) : '—';
    const volStr = `${d.volume ?? '—'} qty`;
    const profit = Number(d.profit ?? 0);
    let resultStr;
    let outcome;
    let kind;
    if (profit > 0) {
      resultStr = `+$${profit.toFixed(2)}`;
      outcome = 'WIN';
      kind = 'win';
    } else if (profit < 0) {
      resultStr = `-$${Math.abs(profit).toFixed(2)}`;
      outcome = 'SL HIT';
      kind = 'loss';
    } else {
      resultStr = 'Fill';
      outcome = 'OPEN';
      kind = 'open';
    }
    return [timeStr, dir, 'BZX', priceStr, volStr, d.symbol ?? 'XAUUSDT', resultStr, outcome, side, kind];
  });
}

export function binanceDealsDailyPnl(deals) {
  if (!Array.isArray(deals) || !deals.length) return 0;
  const now = new Date();
  const todayStart = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  let total = 0;
  for (const d of deals) {
    if (!isBinanceDealRow(d)) continue;
    if ((d.time ?? 0) < todayStart) continue;
    total += Number(d.profit ?? 0);
  }
  return total;
}

export function binanceDealsTotalPnl(deals) {
  if (!Array.isArray(deals) || !deals.length) return 0;
  let total = 0;
  for (const d of deals) {
    if (!isBinanceDealRow(d)) continue;
    total += Number(d.profit ?? 0);
  }
  return total;
}

export function brokerDealsDailyPnl(deals) {
  return binanceDealsDailyPnl(deals);
}

export function brokerDealsTotalPnl(deals) {
  return binanceDealsTotalPnl(deals);
}
