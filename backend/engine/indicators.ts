import type { Bar } from './types';

export function closes(bars: Bar[]): number[] {
  return bars.map((b) => b.c);
}

export function highs(bars: Bar[]): number[] {
  return bars.map((b) => b.h);
}

export function lows(bars: Bar[]): number[] {
  return bars.map((b) => b.l);
}

export function opens(bars: Bar[]): number[] {
  return bars.map((b) => b.o);
}

/** Wilder RMA (Pine ta.rma). */
export function rma(values: number[], len: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (len <= 0 || values.length === 0) return out;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (i < len - 1) {
      out[i] = null;
      continue;
    }
    if (i === len - 1) {
      let sum = 0;
      for (let j = 0; j < len; j++) sum += values[j];
      out[i] = sum / len;
      continue;
    }
    const prev = out[i - 1];
    if (prev == null) {
      out[i] = null;
      continue;
    }
    out[i] = (prev * (len - 1) + v) / len;
  }
  return out;
}

export function trueRange(h: number[], l: number[], c: number[]): number[] {
  const tr: number[] = [];
  for (let i = 0; i < h.length; i++) {
    const hl = h[i] - l[i];
    if (i === 0) {
      tr.push(hl);
    } else {
      const pc = c[i - 1];
      tr.push(Math.max(hl, Math.abs(h[i] - pc), Math.abs(l[i] - pc)));
    }
  }
  return tr;
}

/** Pine ta.atr(len) — RMA of true range. */
export function atr(bars: Bar[], len: number): (number | null)[] {
  const h = highs(bars);
  const l = lows(bars);
  const c = closes(bars);
  return rma(trueRange(h, l, c), len);
}

export function lastFinite<T>(arr: (T | null)[]): T | null {
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i];
    if (v !== null && v !== undefined && Number.isFinite(v as number)) return v as T;
  }
  return null;
}

/** Pine ta.ema(source, len). */
export function ema(values: number[], len: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (len <= 0 || values.length === 0) return out;
  const alpha = 2 / (len + 1);
  for (let i = 0; i < values.length; i++) {
    if (i === 0) {
      out[i] = values[0];
      continue;
    }
    const prev = out[i - 1];
    if (prev == null) {
      out[i] = values[i];
      continue;
    }
    out[i] = alpha * values[i] + (1 - alpha) * prev;
  }
  return out;
}

export function isPivotHigh(high: number[], i: number, L: number, R: number): boolean {
  if (i - L < 0 || i + R >= high.length) return false;
  const pv = high[i];
  for (let k = i - L; k <= i + R; k++) {
    if (k !== i && high[k] >= pv) return false;
  }
  return true;
}

export function isPivotLow(low: number[], i: number, L: number, R: number): boolean {
  if (i - L < 0 || i + R >= low.length) return false;
  const pv = low[i];
  for (let k = i - L; k <= i + R; k++) {
    if (k !== i && low[k] <= pv) return false;
  }
  return true;
}

export function pivotHighConfirmAt(high: number[], conf: number, L: number, R: number): number | null {
  const center = conf - R;
  if (center < L || center >= high.length - R) return null;
  return isPivotHigh(high, center, L, R) ? high[center] : null;
}

export function pivotLowConfirmAt(low: number[], conf: number, L: number, R: number): number | null {
  const center = conf - R;
  if (center < L || center >= low.length - R) return null;
  return isPivotLow(low, center, L, R) ? low[center] : null;
}
