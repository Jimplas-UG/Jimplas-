import type { Bar } from '../../engine/types';
import { dedupeByTime } from './tradingViewChartCsv';

function splitMt5Line(line: string): string[] {
  if ((line.match(/\t/g) || []).length >= 2) return line.split('\t').map((c) => c.trim());
  return line.split(',').map((c) => c.trim().replace(/^"+|"+$/g, ''));
}

function normHeader(s: string): string {
  return s.replace(/^\ufeff/, '').replace(/^"+|"+$/g, '').replace(/[<>]/g, '').trim().toLowerCase();
}

function parsePrice(cell: string): number | null {
  const x = Number(String(cell).replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(x) ? x : null;
}

/**
 * MT5 "Export Bars" uses YYYY.MM.DD + HH:MM:SS without timezone.
 * We combine components as **UTC** for stable ordering; if your IC Markets server is EET,
 * set `MT5_CSV_OFFSET_MS` (e.g. `-7200000` to shift two hours) so session gates line up.
 */
function parseMt5DateTimeUtc(dateCell: string, timeCell: string): number | null {
  const dateStr = dateCell.trim().replace(/\//g, '.');
  const dp = dateStr.split('.');
  if (dp.length < 3) return null;
  const y = Number(dp[0]);
  const mo = Number(dp[1]);
  const da = Number(dp[2]);
  if (![y, mo, da].every(Number.isFinite)) return null;
  const tp = timeCell.trim().split(':');
  const hh = Number(tp[0] ?? 0);
  const mm = Number(tp[1] ?? 0);
  const ss = Number(tp[2] ?? 0);
  return Date.UTC(y, mo - 1, da, hh, mm, ss);
}

/**
 * MetaTrader 5 **View → Symbols → Bars → Export Bars** CSV (tab or comma).
 * IC Markets and other brokers use this same MT5 export for XAUUSD, etc.
 *
 * Expects columns DATE, TIME, OPEN, HIGH, LOW, CLOSE (and optional TICKVOL/VOL/SPREAD), or a headerless
 * row starting with `YYYY.MM.DD` in the first column.
 */
export function parseMetaTrader5ExportBarsCsv(text: string): Bar[] {
  const offset = Number(process.env.MT5_CSV_OFFSET_MS ?? '0');
  const off = Number.isFinite(offset) ? offset : 0;
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  if (!lines.length) return [];

  const row0 = splitMt5Line(lines[0]!);
  const headers = row0.map(normHeader);
  let di: number;
  let ti: number;
  let oi: number;
  let hi: number;
  let li: number;
  let ci: number;
  let firstDataRow: number;

  const looksLikeData = /^\d{4}[./]\d{1,2}[./]\d{1,2}/.test((row0[0] ?? '').trim());
  if (looksLikeData) {
    di = 0;
    ti = 1;
    oi = 2;
    hi = 3;
    li = 4;
    ci = 5;
    firstDataRow = 0;
  } else {
    di = headers.findIndex((h) => h === 'date');
    ti = headers.findIndex((h) => h === 'time');
    oi = headers.findIndex((h) => h === 'open');
    hi = headers.findIndex((h) => h === 'high');
    li = headers.findIndex((h) => h === 'low');
    ci = headers.findIndex((h) => h === 'close');
    if (di < 0 || ti < 0 || oi < 0 || hi < 0 || li < 0 || ci < 0) {
      throw new Error(
        'MT5 CSV: need columns DATE, TIME, OPEN, HIGH, LOW, CLOSE (from MT5 Symbols → Bars → Export Bars).'
      );
    }
    firstDataRow = 1;
  }

  const out: Bar[] = [];
  for (let r = firstDataRow; r < lines.length; r++) {
    const cells = splitMt5Line(lines[r]!);
    if (cells.length <= Math.max(di, ti, oi, hi, li, ci)) continue;
    const tRaw = parseMt5DateTimeUtc(cells[di] ?? '', cells[ti] ?? '');
    if (tRaw == null) continue;
    const o = parsePrice(cells[oi] ?? '');
    const h = parsePrice(cells[hi] ?? '');
    const l = parsePrice(cells[li] ?? '');
    const c = parsePrice(cells[ci] ?? '');
    if (o == null || h == null || l == null || c == null) continue;
    out.push({ t: tRaw + off, o, h, l, c });
  }
  return dedupeByTime(out);
}

/** Alias: IC Markets historical bars are obtained the same way as any MT5 broker export. */
export function parseIcMarketsMt5ExportBarsCsv(text: string): Bar[] {
  return parseMetaTrader5ExportBarsCsv(text);
}
