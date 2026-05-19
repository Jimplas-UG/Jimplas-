import { highs, lows, pivotHighConfirmAt, pivotLowConfirmAt } from './indicators';
import type { Bar, BilshenzEngineConfig, SrStacks } from './types';

export type SrReplayResult = SrStacks & {
  nearestRes: number | null;
  nearestSup: number | null;
  poiRes: number | null;
  poiSup: number | null;
  flipSupLevel: number | null;
  flipResLevel: number | null;
  prevNearestRes: number | null;
  prevNearestSup: number | null;
};

function fImmRes(arrPh: number[], close: number, zone: number): number | null {
  let r: number | null = null;
  for (let i = 0; i < arrPh.length; i++) {
    const v = arrPh[i];
    if (v > close + zone) {
      if (r === null || v < r) r = v;
    }
  }
  return r;
}

function fImmSup(arrPl: number[], close: number, zone: number): number | null {
  let s: number | null = null;
  for (let i = 0; i < arrPl.length; i++) {
    const v = arrPl[i];
    if (v < close - zone) {
      if (s === null || v > s) s = v;
    }
  }
  return s;
}

function fPoiRes(arrPh: number[], close: number, zone: number, imm: number | null): number | null {
  let r: number | null = null;
  for (let i = 0; i < arrPh.length; i++) {
    const v = arrPh[i];
    if (v > close + zone && (imm == null || v > imm + zone)) {
      if (r === null || v < r) r = v;
    }
  }
  return r;
}

function fPoiSup(arrPl: number[], close: number, zone: number, imm: number | null): number | null {
  let s: number | null = null;
  for (let i = 0; i < arrPl.length; i++) {
    const v = arrPl[i];
    if (v < close - zone && (imm == null || v < imm - zone)) {
      if (s === null || v > s) s = v;
    }
  }
  return s;
}

/** Pine: nearest resistance above price from r1,r2,r3. */
export function nearestResStack(r1: number | null, r2: number | null, r3: number | null, close: number): number | null {
  if (r1 != null && r1 > close) return r1;
  if (r2 != null && r2 > close) return r2;
  if (r3 != null && r3 > close) return r3;
  return null;
}

/** Pine: nearest support below price from s1,s2,s3. */
export function nearestSupStack(s1: number | null, s2: number | null, s3: number | null, close: number): number | null {
  if (s1 != null && s1 < close) return s1;
  if (s2 != null && s2 < close) return s2;
  if (s3 != null && s3 < close) return s3;
  return null;
}

/** Pine BILSHENZ v3.2 Section 4 — pivot arrays, immediate S/R, POI, flip levels. */
export function replaySrEngine(m30: Bar[], cfg: BilshenzEngineConfig): SrReplayResult {
  const H = highs(m30);
  const L = lows(m30);
  const C = m30.map((b) => b.c);
  const n = m30.length;
  const Lp = cfg.pivotLeft;
  const Rp = cfg.pivotRight;
  const srMax = cfg.srHistoryMax;
  const zone = cfg.zoneHalfWidthPips * cfg.pipSize;

  const arrPh: number[] = [];
  const arrPl: number[] = [];

  let flipSupLevel: number | null = null;
  let flipResLevel: number | null = null;

  let r1Flipped = false;
  let r2Flipped = false;
  let r3Flipped = false;
  let s1Flipped = false;
  let s2Flipped = false;
  let s3Flipped = false;

  const histImmRes: (number | null)[] = new Array(n).fill(null);
  const histImmSup: (number | null)[] = new Array(n).fill(null);

  const start = Lp + Rp;
  for (let conf = start; conf < n; conf++) {
    const sh = pivotHighConfirmAt(H, conf, Lp, Rp);
    if (sh != null) {
      arrPh.unshift(sh);
      if (arrPh.length > srMax) arrPh.pop();
    }
    const sl = pivotLowConfirmAt(L, conf, Lp, Rp);
    if (sl != null) {
      arrPl.unshift(sl);
      if (arrPl.length > srMax) arrPl.pop();
    }

    const cl = C[conf];
    const cl1 = conf >= 1 ? C[conf - 1] : cl;

    for (let i = 0; i < arrPh.length; i++) {
      const v = arrPh[i];
      if (cl > v + zone && cl1 <= v + zone) {
        if (flipSupLevel == null || Math.abs(v - flipSupLevel) > zone * 2) flipSupLevel = v;
      }
    }
    for (let i = 0; i < arrPl.length; i++) {
      const v = arrPl[i];
      if (cl < v - zone && cl1 >= v - zone) {
        if (flipResLevel == null || Math.abs(v - flipResLevel) > zone * 2) flipResLevel = v;
      }
    }

    if (arrPh.length > 0 && arrPh[0] != null && cl > arrPh[0] + zone) r1Flipped = true;
    if (arrPh.length > 1 && arrPh[1] != null && cl > arrPh[1] + zone) r2Flipped = true;
    if (arrPh.length > 2 && arrPh[2] != null && cl > arrPh[2] + zone) r3Flipped = true;
    if (arrPl.length > 0 && arrPl[0] != null && cl < arrPl[0] - zone) s1Flipped = true;
    if (arrPl.length > 1 && arrPl[1] != null && cl < arrPl[1] - zone) s2Flipped = true;
    if (arrPl.length > 2 && arrPl[2] != null && cl < arrPl[2] - zone) s3Flipped = true;
    if (sh != null) r1Flipped = false;
    if (sl != null) s1Flipped = false;

    histImmRes[conf] = fImmRes(arrPh, cl, zone);
    histImmSup[conf] = fImmSup(arrPl, cl, zone);
  }

  const close = C[n - 1];
  const r1 = arrPh[0] ?? null;
  const r2 = arrPh[1] ?? null;
  const r3 = arrPh[2] ?? null;
  const s1 = arrPl[0] ?? null;
  const s2 = arrPl[1] ?? null;
  const s3 = arrPl[2] ?? null;
  const nearestRes = nearestResStack(r1, r2, r3, close);
  const nearestSup = nearestSupStack(s1, s2, s3, close);
  const immRes = histImmRes[n - 1];
  const immSup = histImmSup[n - 1];
  const poiRes = fPoiRes(arrPh, close, zone, immRes);
  const poiSup = fPoiSup(arrPl, close, zone, immSup);

  const prevClose = n >= 2 ? C[n - 2] : close;
  const prevNearestRes = nearestResStack(r1, r2, r3, prevClose);
  const prevNearestSup = nearestSupStack(s1, s2, s3, prevClose);

  return {
    r1,
    r2,
    r3,
    s1,
    s2,
    s3,
    r1Flipped,
    r2Flipped,
    r3Flipped,
    s1Flipped,
    s2Flipped,
    s3Flipped,
    nearestRes,
    nearestSup,
    poiRes,
    poiSup,
    flipSupLevel,
    flipResLevel,
    prevNearestRes,
    prevNearestSup,
  };
}

/**
 * Single O(n) pass: S&R state after each bar closes (same math as {@link replaySrEngine} on prefixes).
 * `out[i]` is the snapshot for the chart at bar index `i` (inclusive of that bar’s close).
 */
export function replaySrBarByBar(m30: Bar[], cfg: BilshenzEngineConfig): SrReplayResult[] {
  const H = highs(m30);
  const L = lows(m30);
  const C = m30.map((b) => b.c);
  const n = m30.length;
  const Lp = cfg.pivotLeft;
  const Rp = cfg.pivotRight;
  const srMax = cfg.srHistoryMax;
  const zone = cfg.zoneHalfWidthPips * cfg.pipSize;

  const arrPh: number[] = [];
  const arrPl: number[] = [];
  let flipSupLevel: number | null = null;
  let flipResLevel: number | null = null;
  let r1Flipped = false;
  let r2Flipped = false;
  let r3Flipped = false;
  let s1Flipped = false;
  let s2Flipped = false;
  let s3Flipped = false;

  const out: SrReplayResult[] = new Array(n);
  const empty: SrReplayResult = {
    r1: null,
    r2: null,
    r3: null,
    s1: null,
    s2: null,
    s3: null,
    r1Flipped: false,
    r2Flipped: false,
    r3Flipped: false,
    s1Flipped: false,
    s2Flipped: false,
    s3Flipped: false,
    nearestRes: null,
    nearestSup: null,
    poiRes: null,
    poiSup: null,
    flipSupLevel: null,
    flipResLevel: null,
    prevNearestRes: null,
    prevNearestSup: null,
  };
  for (let i = 0; i < n; i++) out[i] = { ...empty };

  const start = Lp + Rp;
  for (let conf = start; conf < n; conf++) {
    const sh = pivotHighConfirmAt(H, conf, Lp, Rp);
    if (sh != null) {
      arrPh.unshift(sh);
      if (arrPh.length > srMax) arrPh.pop();
    }
    const sl = pivotLowConfirmAt(L, conf, Lp, Rp);
    if (sl != null) {
      arrPl.unshift(sl);
      if (arrPl.length > srMax) arrPl.pop();
    }

    const cl = C[conf];
    const cl1 = conf >= 1 ? C[conf - 1] : cl;

    for (let i = 0; i < arrPh.length; i++) {
      const v = arrPh[i];
      if (cl > v + zone && cl1 <= v + zone) {
        if (flipSupLevel == null || Math.abs(v - flipSupLevel) > zone * 2) flipSupLevel = v;
      }
    }
    for (let i = 0; i < arrPl.length; i++) {
      const v = arrPl[i];
      if (cl < v - zone && cl1 >= v - zone) {
        if (flipResLevel == null || Math.abs(v - flipResLevel) > zone * 2) flipResLevel = v;
      }
    }

    if (arrPh.length > 0 && arrPh[0] != null && cl > arrPh[0] + zone) r1Flipped = true;
    if (arrPh.length > 1 && arrPh[1] != null && cl > arrPh[1] + zone) r2Flipped = true;
    if (arrPh.length > 2 && arrPh[2] != null && cl > arrPh[2] + zone) r3Flipped = true;
    if (arrPl.length > 0 && arrPl[0] != null && cl < arrPl[0] - zone) s1Flipped = true;
    if (arrPl.length > 1 && arrPl[1] != null && cl < arrPl[1] - zone) s2Flipped = true;
    if (arrPl.length > 2 && arrPl[2] != null && cl < arrPl[2] - zone) s3Flipped = true;
    if (sh != null) r1Flipped = false;
    if (sl != null) s1Flipped = false;

    const r1 = arrPh[0] ?? null;
    const r2 = arrPh[1] ?? null;
    const r3 = arrPh[2] ?? null;
    const s1 = arrPl[0] ?? null;
    const s2 = arrPl[1] ?? null;
    const s3 = arrPl[2] ?? null;
    const nearestRes = nearestResStack(r1, r2, r3, cl);
    const nearestSup = nearestSupStack(s1, s2, s3, cl);
    const immRes = fImmRes(arrPh, cl, zone);
    const immSup = fImmSup(arrPl, cl, zone);
    const poiRes = fPoiRes(arrPh, cl, zone, immRes);
    const poiSup = fPoiSup(arrPl, cl, zone, immSup);
    const prevClose = conf >= 1 ? C[conf - 1] : cl;
    const prevNearestRes = nearestResStack(r1, r2, r3, prevClose);
    const prevNearestSup = nearestSupStack(s1, s2, s3, prevClose);

    out[conf] = {
      r1,
      r2,
      r3,
      s1,
      s2,
      s3,
      r1Flipped,
      r2Flipped,
      r3Flipped,
      s1Flipped,
      s2Flipped,
      s3Flipped,
      nearestRes,
      nearestSup,
      poiRes,
      poiSup,
      flipSupLevel,
      flipResLevel,
      prevNearestRes,
      prevNearestSup,
    };
  }
  return out;
}
