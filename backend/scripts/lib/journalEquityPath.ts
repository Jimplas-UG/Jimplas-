/**
 * Replay compounding equity from closed journal rows (matches run-xau-12mo-yahoo-backtest logic).
 */
import type { BilshenzEngineConfig, TradeJournalRow } from '../../engine/types';
import { riskScaleForSlTpMismatch } from '../../engine/tradeGeometry';

export type RealisticCosts = {
  spreadPips: number;
  slippagePipsPerSide: number;
  lossSlPips: (structural: number, sizing: number) => number;
};

export function pnlUsdForClosed(
  row: TradeJournalRow,
  outcome: 'WIN' | 'LOSS' | 'HALF_LOSS',
  pipSize: number,
  simUsdPerEnginePip: number,
  riskUsd: number,
  cfg: BilshenzEngineConfig,
  realistic?: RealisticCosts | null
): number {
  const structuralSl = Math.abs(row.entry - row.sl) / pipSize;
  if (structuralSl <= 0 || !Number.isFinite(row.tp1)) return 0;
  const sizingSl = cfg.journalSizingSlPips > 0 ? cfg.journalSizingSlPips : structuralSl;
  const scale = cfg.riskScaleWideStops ? riskScaleForSlTpMismatch(structuralSl, cfg) : 1;
  const adjRisk = riskUsd * scale;
  const lots = adjRisk / (sizingSl * simUsdPerEnginePip);
  const pipUsd = simUsdPerEnginePip;

  if (realistic) {
    const rtPips = realistic.spreadPips + realistic.slippagePipsPerSide * 2;
    const frictionUsd = rtPips * pipUsd * lots;
    if (outcome === 'LOSS') {
      const lossPips = realistic.lossSlPips(structuralSl, sizingSl);
      return -lossPips * pipUsd * lots - frictionUsd;
    }
    if (outcome === 'HALF_LOSS') {
      const fullLossPips = realistic.lossSlPips(structuralSl, sizingSl);
      const lossPips = fullLossPips * 0.5;
      return -lossPips * pipUsd * lots - frictionUsd;
    }
    const tpPips = Math.abs(row.tp1! - row.entry) / pipSize;
    const netTp = Math.max(0, tpPips - rtPips);
    return netTp * pipUsd * lots;
  }

  if (outcome === 'LOSS') return -adjRisk;
  if (outcome === 'HALF_LOSS') return -adjRisk * 0.5;
  const tpPips = Math.abs(row.tp1! - row.entry) / pipSize;
  return tpPips * pipUsd * lots;
}

export function equityAfterAutoTrades(
  closedChrono: TradeJournalRow[],
  pipSize: number,
  simUsdPerEnginePip: number,
  startEquity: number,
  riskPct: number,
  cfg: BilshenzEngineConfig,
  realistic?: RealisticCosts | null
): { endEquity: number; series: { bar: number; equity: number; pnl: number }[] } {
  let equity = startEquity;
  const series: { bar: number; equity: number; pnl: number }[] = [];
  for (const r of closedChrono) {
    if (r.out !== 'WIN' && r.out !== 'LOSS' && r.out !== 'HALF_LOSS') continue;
    const riskUsd = equity * riskPct;
    const pnl = pnlUsdForClosed(r, r.out, pipSize, simUsdPerEnginePip, riskUsd, cfg, realistic);
    equity += pnl;
    series.push({ bar: r.barIndex, equity, pnl });
  }
  return { endEquity: equity, series };
}

export function maxDrawdownFromSeries(startEquity: number, series: { equity: number }[]): number {
  let peak = startEquity;
  let maxDd = 0;
  for (const s of series) {
    if (s.equity > peak) peak = s.equity;
    const dd = peak - s.equity;
    if (dd > maxDd) maxDd = dd;
  }
  return maxDd;
}

/** Simple deterministic PRNG for reproducible Monte Carlo (Mulberry32). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function rand() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function shuffleInPlace<T>(arr: T[], rand: () => number): void {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [arr[i], arr[j]] = [arr[j]!, arr[i]!];
  }
}

export function sampleWithReplacement<T>(source: T[], n: number, rand: () => number): T[] {
  const out: T[] = [];
  const L = source.length;
  if (L === 0) return out;
  for (let i = 0; i < n; i++) {
    out.push(source[Math.floor(rand() * L)]!);
  }
  return out;
}

export function cloneJournalRow(r: TradeJournalRow): TradeJournalRow {
  return { ...r };
}
