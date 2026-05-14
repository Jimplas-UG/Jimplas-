import type { Bar, MarketBundle } from './types';

const M30_MS = 30 * 60 * 1000;

function makeBar(t: number, o: number, h: number, l: number, c: number): Bar {
  return { t, o, h, l, c };
}

/** Deterministic PRNG (Mulberry32) for reproducible synthetic series. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Downsample M30 closes into pseudo HTF bars (OHLC = close stub) for engine feed. */
function compressBars(src: Bar[], every: number): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < src.length; i += every) {
    const chunk = src.slice(i, i + every);
    if (!chunk.length) continue;
    const o = chunk[0].o;
    const c = chunk[chunk.length - 1].c;
    const h = Math.max(...chunk.map((b) => b.h));
    const l = Math.min(...chunk.map((b) => b.l));
    const t = chunk[chunk.length - 1].t;
    out.push(makeBar(t, o, h, l, c));
  }
  return out;
}

/**
 * Builds a coherent multi-TF bundle ending at `anchorClose` (synthetic path).
 * Used until a real market API backs the bundle; pivot/SR logic is real on this series.
 *
 * @param opts.seed — if set, uses deterministic RNG (reproducible backtests).
 * @param opts.volatilityMul — scales candle body/wick noise (default 1). Use values below 1 for narrower M30 bars so Pine bar-range spread guard does not dominate.
 */
export function buildSyntheticMarketBundle(opts: {
  anchorClose: number;
  anchorTimeMs?: number;
  count?: number;
  seed?: number;
  volatilityMul?: number;
}): MarketBundle {
  const count = opts.count ?? 480;
  const endT = opts.anchorTimeMs ?? Date.now();
  const vm = opts.volatilityMul != null && Number.isFinite(opts.volatilityMul) && opts.volatilityMul > 0 ? opts.volatilityMul : 1;
  const rand = opts.seed !== undefined && opts.seed !== null ? mulberry32(opts.seed) : () => Math.random();
  let c = opts.anchorClose;
  const m30: Bar[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const t = endT - i * M30_MS;
    const w = (rand() - 0.5) * 6 * vm;
    const o = c;
    c = parseFloat((c + w).toFixed(2));
    const h = Math.max(o, c) + rand() * 2 * vm;
    const l = Math.min(o, c) - rand() * 2 * vm;
    m30.push(makeBar(t, o, h, l, c));
  }
  const h4 = compressBars(m30, 8);
  const d1 = compressBars(m30, 48);
  const w1 = compressBars(m30, 48 * 5);
  const mn1 = compressBars(m30, 48 * 22);
  const dxyCloseSeries = m30.map((_, i) => 99 + Math.sin(i / 17) * 0.6 + (i / count) * 0.1);
  const us10yCloseSeries = m30.map((_, i) => 4.15 + Math.sin(i / 31) * 0.12);
  return { m30, h4, d1, w1, mn1, dxyCloseSeries, us10yCloseSeries };
}

/** Build HTF + macro stubs from an arbitrary M30 series (e.g. Yahoo GC=F). */
export function buildBundleFromM30Bars(m30: Bar[]): MarketBundle {
  const L = m30.length;
  const dxyCloseSeries = m30.map((_, i) => 99 + Math.sin(i / 17) * 0.6 + (i / Math.max(L, 1)) * 0.05);
  const us10yCloseSeries = m30.map((_, i) => 4.15 + Math.sin(i / 31) * 0.12);
  return {
    m30,
    h4: compressBars(m30, 8),
    d1: compressBars(m30, 48),
    w1: compressBars(m30, 48 * 5),
    mn1: compressBars(m30, 48 * 22),
    dxyCloseSeries,
    us10yCloseSeries,
  };
}

/**
 * Point-in-time bundle for backtest: only M30 bars `0..endInclusive`, HTF series rebuilt from that prefix.
 * Macro series are trimmed / padded to match `m30.length`.
 */
export function sliceMarketBundleToM30End(bundle: MarketBundle, endInclusive: number): MarketBundle {
  const n = bundle.m30.length;
  if (n === 0) return bundle;
  const e = Math.max(0, Math.min(Math.floor(endInclusive), n - 1));
  const m30 = bundle.m30.slice(0, e + 1);
  const L = m30.length;
  let dxy = (bundle.dxyCloseSeries ?? []).slice(0, L);
  let uy = (bundle.us10yCloseSeries ?? []).slice(0, L);
  const padDx = dxy.length ? dxy[dxy.length - 1]! : 99;
  const padUy = uy.length ? uy[uy.length - 1]! : 4.2;
  while (dxy.length < L) dxy.push(padDx);
  while (uy.length < L) uy.push(padUy);
  dxy = dxy.slice(0, L);
  uy = uy.slice(0, L);
  const h4 = compressBars(m30, 8);
  const d1 = compressBars(m30, 48);
  const w1 = compressBars(m30, 48 * 5);
  const mn1 = compressBars(m30, 48 * 22);
  return { m30, h4, d1, w1, mn1, dxyCloseSeries: dxy, us10yCloseSeries: uy };
}

export function patchBundleLast(
  bundle: MarketBundle,
  liveClose: number,
  dxyClose: number,
  us10yClose: number
): MarketBundle {
  const m30 = bundle.m30.map((b, i, arr) =>
    i === arr.length - 1
      ? {
          ...b,
          c: liveClose,
          h: Math.max(b.h, liveClose),
          l: Math.min(b.l, liveClose),
        }
      : b
  );
  const dx = [...bundle.dxyCloseSeries];
  if (dx.length) dx[dx.length - 1] = dxyClose;
  const uy = [...bundle.us10yCloseSeries];
  if (uy.length) uy[uy.length - 1] = us10yClose;
  return { ...bundle, m30, dxyCloseSeries: dx, us10yCloseSeries: uy };
}
