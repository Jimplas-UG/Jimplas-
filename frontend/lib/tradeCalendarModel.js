/** Trade calendar aggregation — week / month / year views from daily PnL rows. */

import { displayDealPnl } from './dealPnl';

export const CALENDAR_VIEWS = [
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
  { id: 'year', label: 'Year' },
  { id: 'all', label: 'All time' },
];

/** Local civil YYYY-MM-DD (matches phone + East Africa desk day). */
export function dayKeyFromTs(tsMs) {
  const d = new Date(Number(tsMs) || 0);
  if (!Number.isFinite(d.getTime()) || d.getTime() <= 0) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function pad2(n) {
  return String(n).padStart(2, '0');
}

export function indexDaysByDate(days) {
  const map = new Map();
  for (const row of days ?? []) {
    if (row?.date) map.set(row.date, row);
  }
  return map;
}

/**
 * Full Sunday→Saturday month matrix with leading/trailing blanks so day 1
 * aligns under the correct weekday and end-of-month days stay on-grid.
 */
export function monthGrid(year, monthIndex0, dayMap) {
  const firstDow = new Date(year, monthIndex0, 1).getDay(); // 0=Sun
  const lastDay = new Date(year, monthIndex0 + 1, 0).getDate();
  const cells = [];

  for (let i = 0; i < firstDow; i++) {
    cells.push({
      date: `pad-s-${year}-${monthIndex0}-${i}`,
      day: '',
      empty: true,
      hasData: false,
      pnl: 0,
      trades: 0,
    });
  }

  for (let d = 1; d <= lastDay; d++) {
    const dt = new Date(year, monthIndex0, d);
    const key = `${year}-${pad2(monthIndex0 + 1)}-${pad2(d)}`;
    const row = dayMap.get(key);
    cells.push({
      date: key,
      day: d,
      dow: dt.getDay(),
      empty: false,
      pnl: Number(row?.pnl ?? 0),
      trades: Number(row?.trades ?? 0),
      hasData: !!row,
    });
  }

  while (cells.length % 7 !== 0) {
    const i = cells.length;
    cells.push({
      date: `pad-e-${year}-${monthIndex0}-${i}`,
      day: '',
      empty: true,
      hasData: false,
      pnl: 0,
      trades: 0,
    });
  }

  return cells;
}

export function weekCells(anchorDate, dayMap) {
  const d = new Date(anchorDate);
  const dow = d.getDay(); // 0=Sun
  const sunday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - dow);
  const cells = [];
  const labels = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  for (let i = 0; i < 7; i++) {
    const dt = new Date(sunday.getFullYear(), sunday.getMonth(), sunday.getDate() + i);
    const key = `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
    const row = dayMap.get(key);
    cells.push({
      date: key,
      day: dt.getDate(),
      label: labels[i],
      empty: false,
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
    const last = new Date(year, m + 1, 0).getDate();
    for (let d = 1; d <= last; d++) {
      const key = `${year}-${pad2(m + 1)}-${pad2(d)}`;
      const row = dayMap.get(key);
      if (!row) continue;
      pnl += Number(row.pnl ?? 0);
      trades += Number(row.trades ?? 0);
      days += 1;
    }
    months.push({
      month: m,
      label: new Date(year, m, 1).toLocaleString('en-US', { month: 'short' }),
      pnl,
      trades,
      hasData: days > 0,
      empty: false,
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
    const shown = displayDealPnl(d);
    if (!ts || Math.abs(shown) < 1e-12) continue;
    if (d.is_close === false) continue;
    const key = dayKeyFromTs(ts);
    if (!key) continue;
    const row = byDay.get(key) ?? { date: key, pnl: 0, trades: 0 };
    row.pnl += shown;
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
  const [y, m, d] = String(dateStr || '').split('-').map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}
