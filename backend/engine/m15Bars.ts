import type { Bar } from './types';

export const M15_MS = 15 * 60 * 1000;
export const M30_MS = 30 * 60 * 1000;

/** Split one M30 bar into two synthetic M15 bars (OHLC envelope preserved). */
export function splitM30BarToM15(b: Bar): [Bar, Bar] {
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
    { t: b.t + M15_MS, o: mid, h: h2, l: l2, c: b.c },
  ];
}

/** Build M15 series from aligned M30 bars (2× bars per M30). */
export function m30ToM15Bars(m30: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (const b of m30) out.push(...splitM30BarToM15(b));
  return out;
}

/** M15 bars whose **close time** is in (afterMs, upToCloseMs]. */
export function closedM15BarsInWindow(m15: Bar[], afterCloseMs: number, upToCloseMs: number): Bar[] {
  return m15.filter((b) => {
    const closeMs = b.t + M15_MS;
    return closeMs > afterCloseMs && closeMs <= upToCloseMs;
  });
}
