/** Trade calendar aggregation — week / month / year views from daily PnL rows. */

export const CALENDAR_VIEWS = [
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
  { id: 'year', label: 'Year' },
  { id: 'all', label: 'All time' },
];

function parseDayKey(dateStr) {
  const [y, m, d] = String(dateStr || '').split('-').map(Number);
  if (!y || !m || !d) return null;
  return new Date(Date.UTC(y, m - 1, d));
}

export function indexDaysByDate(days) {
  const map = new Map();
  for (const row of days ?? []) {
    if (row?.date) map.set(row.date, row);
  }
  return map;
}

export function monthGrid(year, monthIndex0, dayMap) {
  const first = new Date(Date.UTC(year, monthIndex0, 1));
  const last = new Date(Date.UTC(year, monthIndex0 + 1, 0));
  const cells = [];
  for (let d = 1; d <= last.getUTCDate(); d++) {
    const dt = new Date(Date.UTC(year, monthIndex0, d));
    const dow = dt.getUTCDay();
    if (dow === 0 || dow === 6) continue;
    const key = `${year}-${String(monthIndex0 + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const row = dayMap.get(key);
    cells.push({
      date: key,
      day: d,
      dow,
      pnl: Number(row?.pnl ?? 0),
      trades: Number(row?.trades ?? 0),
      hasData: !!row,
    });
  }
  return cells;
}

export function weekCells(anchorDate, dayMap) {
  const d = new Date(anchorDate);
  const dow = d.getUTCDay();
  const mondayOffset = dow === 0 ? -6 : 1 - dow;
  const monday = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + mondayOffset));
  const cells = [];
  for (let i = 0; i < 5; i++) {
    const dt = new Date(monday.getTime() + i * 86400000);
    const key = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
    const row = dayMap.get(key);
    cells.push({
      date: key,
      day: dt.getUTCDate(),
      label: ['MON', 'TUE', 'WED', 'THU', 'FRI'][i],
      pnl: Number(row?.pnl ?? 0),
      trades: Number(row?.trades ?? 0),
      hasData: !!row,
    });
  }
  return cells;
}

export function yearMonths(year, dayMap) {
  const months = [];
  for (let m = 0; m < 12; m++) {
    let pnl = 0;
    let trades = 0;
    let days = 0;
    const last = new Date(Date.UTC(year, m + 1, 0)).getUTCDate();
    for (let d = 1; d <= last; d++) {
      const key = `${year}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      const row = dayMap.get(key);
      if (!row) continue;
      pnl += Number(row.pnl ?? 0);
      trades += Number(row.trades ?? 0);
      days += 1;
    }
    months.push({
      month: m,
      label: new Date(Date.UTC(year, m, 1)).toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }),
      pnl,
      trades,
      hasData: days > 0,
    });
  }
  return months;
}

export function sumRangePnl(days, startKey, endKey) {
  let total = 0;
  for (const row of days ?? []) {
    if (row.date >= startKey && row.date <= endKey) total += Number(row.pnl ?? 0);
  }
  return total;
}

export function aggregateDealsToDays(deals) {
  const byDay = new Map();
  for (const d of deals ?? []) {
    const ts = Number(d.time ?? 0);
    const pnl = Number(d.profit ?? 0);
    if (!ts || Math.abs(pnl) < 1e-12) continue;
    const key = new Date(ts).toISOString().slice(0, 10);
    const row = byDay.get(key) ?? { date: key, pnl: 0, trades: 0 };
    row.pnl += pnl;
    row.trades += 1;
    byDay.set(key, row);
  }
  return [...byDay.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function fmtCalendarMoney(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  const sign = x >= 0 ? '+' : '';
  return `${sign}${x.toFixed(2)}`;
}

export function parseDayKeyUtc(dateStr) {
  return parseDayKey(dateStr);
}
