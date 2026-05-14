import type { Bar } from './types';

export function pdhPdl(d1: Bar[]): { pdh: number | null; pdl: number | null } {
  if (d1.length < 2) return { pdh: null, pdl: null };
  const prev = d1[d1.length - 2];
  return { pdh: prev.h, pdl: prev.l };
}

export function weeklyPrevHl(w1: Bar[]): { wh: number | null; wl: number | null } {
  if (w1.length < 2) return { wh: null, wl: null };
  const prev = w1[w1.length - 2];
  return { wh: prev.h, wl: prev.l };
}

export function monthlyPrevHl(m1: Bar[]): { mh: number | null; ml: number | null } {
  if (m1.length < 2) return { mh: null, ml: null };
  const prev = m1[m1.length - 2];
  return { mh: prev.h, ml: prev.l };
}
