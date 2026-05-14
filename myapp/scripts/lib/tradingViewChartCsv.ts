import type { Bar } from '../../engine/types';

const M30_MS = 30 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

function splitCsvLine(line: string, delim: string): string[] {
  const out: string[] = [];
  let cur = '';
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!;
    if (ch === '"') {
      inQ = !inQ;
      continue;
    }
    if (!inQ && ch === delim) {
      out.push(cur.trim());
      cur = '';
      continue;
    }
    cur += ch;
  }
  out.push(cur.trim());
  return out;
}

function detectDelimiter(line: string): string {
  const tabs = (line.match(/\t/g) || []).length;
  const semi = (line.match(/;/g) || []).length;
  const comma = (line.match(/,/g) || []).length;
  if (tabs >= 2) return '\t';
  if (semi > comma) return ';';
  return ',';
}

function normHeader(h: string): string {
  return h.replace(/^\ufeff/, '').replace(/^"+|"+$/g, '').trim().toLowerCase();
}

function parseTimeMs(cell: string): number | null {
  const t = cell.replace(/^"+|"+$/g, '').trim();
  if (!t) return null;
  const num = Number(t);
  if (Number.isFinite(num) && num > 1e12) return num;
  if (Number.isFinite(num) && num > 1e9 && num < 1e12) return num * 1000;
  const ms = Date.parse(t);
  return Number.isNaN(ms) ? null : ms;
}

function parsePrice(cell: string): number | null {
  const s = String(cell).replace(/^"+|"+$/g, '').replace(/\s/g, '').replace(',', '.');
  const x = Number(s);
  return Number.isFinite(x) ? x : null;
}

function rowLooksLikeOhlcRow(cells: string[], tIdx: number, oIdx: number, hIdx: number, lIdx: number, cIdx: number): boolean {
  const t = parseTimeMs(cells[tIdx] ?? '');
  const o = parsePrice(cells[oIdx] ?? '');
  const h = parsePrice(cells[hIdx] ?? '');
  const l = parsePrice(cells[lIdx] ?? '');
  const c = parsePrice(cells[cIdx] ?? '');
  return t != null && o != null && h != null && l != null && c != null;
}

function findOhlcColumnIndices(headerCells: string[]): { t: number; o: number; h: number; l: number; c: number } | null {
  const names = headerCells.map(normHeader);
  const find = (pred: (s: string) => boolean) => names.findIndex(pred);

  const ti = find((s) => /^time(\s|\(|$)/.test(s) || s === 'date' || s === 'datetime' || s === 'timestamp');
  const t = ti >= 0 ? ti : 0;
  const o = find((s) => s === 'open');
  const h = find((s) => s === 'high');
  const l = find((s) => s === 'low');
  const c = find((s) => s === 'close');
  if (o >= 0 && h >= 0 && l >= 0 && c >= 0) return { t, o, h, l, c };
  return null;
}

export function dedupeByTime(bars: Bar[]): Bar[] {
  const m = new Map<number, Bar>();
  for (const b of bars) m.set(b.t, b);
  return [...m.values()].sort((a, b) => a.t - b.t);
}

function medianStepMs(bars: Bar[]): number {
  if (bars.length < 3) return M30_MS;
  const deltas: number[] = [];
  const cap = Math.min(bars.length - 1, 2000);
  for (let i = 1; i <= cap; i++) deltas.push(bars[i]!.t - bars[i - 1]!.t);
  deltas.sort((a, b) => a - b);
  return deltas[Math.floor(deltas.length / 2)]!;
}

/** Split one hourly bar into two M30 bars; OHLC envelope matches the hour. */
export function upsampleHourlyBarToTwoM30(b: Bar): [Bar, Bar] {
  const mid = (b.o + b.c) / 2;
  let h1 = Math.max(b.o, mid);
  let l1 = Math.min(b.o, mid);
  let h2 = Math.max(mid, b.c);
  let l2 = Math.min(mid, b.c);
  const unionH = Math.max(h1, h2);
  const unionL = Math.min(l1, l2);
  if (b.h > unionH) {
    const extra = b.h - unionH;
    if (h1 >= h2) h1 += extra;
    else h2 += extra;
  }
  if (b.l < unionL) {
    const extra = unionL - b.l;
    if (l1 <= l2) l1 -= extra;
    else l2 -= extra;
  }
  return [
    { t: b.t, o: b.o, h: h1, l: l1, c: mid },
    { t: b.t + M30_MS, o: mid, h: h2, l: l2, c: b.c },
  ];
}

export function hourlyBarsToM30Series(hourly: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (const h of hourly) out.push(...upsampleHourlyBarToTwoM30(h));
  return out;
}

/**
 * Parse TradingView Supercharts “Download chart data…” CSV (comma, semicolon, or tab).
 * Expects columns time + open/high/low/close (extra indicator columns are ignored if headers are present).
 */
export function parseTradingViewChartCsv(text: string): Bar[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  if (!lines.length) return [];

  const delim = detectDelimiter(lines[0]!);
  const firstCells = splitCsvLine(lines[0]!, delim);
  const idx = findOhlcColumnIndices(firstCells);
  let dataStart = 1;
  let cols = idx;
  if (!cols) {
    const second = splitCsvLine(lines[1] ?? '', delim);
    if (second.length >= 5 && rowLooksLikeOhlcRow(second, 0, 1, 2, 3, 4)) {
      cols = { t: 0, o: 1, h: 2, l: 3, c: 4 };
      dataStart = 0;
    } else {
      throw new Error(
        'Could not detect Time + Open/High/Low/Close columns. Export from TradingView with standard OHLC visible.'
      );
    }
  }

  const out: Bar[] = [];
  for (let li = dataStart; li < lines.length; li++) {
    const cells = splitCsvLine(lines[li]!, delim);
    if (cells.length <= Math.max(cols.t, cols.o, cols.h, cols.l, cols.c)) continue;
    const t = parseTimeMs(cells[cols.t] ?? '');
    const o = parsePrice(cells[cols.o] ?? '');
    const h = parsePrice(cells[cols.h] ?? '');
    const l = parsePrice(cells[cols.l] ?? '');
    const c = parsePrice(cells[cols.c] ?? '');
    if (t == null || o == null || h == null || l == null || c == null) continue;
    out.push({ t, o, h, l, c });
  }
  return dedupeByTime(out);
}

/** Accept native ~30m bars, or ~1h bars upsampled to M30 for the engine. */
export function maybeUpsampleBarsToM30(bars: Bar[]): Bar[] {
  const sorted = dedupeByTime(bars);
  if (sorted.length < 2) return sorted;
  const med = medianStepMs(sorted);
  if (med >= M30_MS * 0.82 && med <= M30_MS * 1.22) return sorted;
  if (med >= HOUR_MS * 0.88 && med <= HOUR_MS * 1.18) return hourlyBarsToM30Series(sorted);
  throw new Error(
    `CSV bar spacing ≈ ${(med / 60000).toFixed(1)} min; export **30m** or **1h** bars (MT5 Symbols → Bars, or TradingView).`
  );
}
