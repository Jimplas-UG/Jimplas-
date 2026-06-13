/**
 * Binance Futures tick-based units (execution + risk boundary).
 * Frozen strategy engine keeps pipSize internally (= strategy tick 0.1 for XAU).
 */
import {
  quantityFromRiskUsd,
  roundToStepSize,
  roundToTickSize,
  type SymbolSpec,
} from './quantityMath';

export { quantityFromRiskUsd, roundToStepSize, roundToTickSize };

export const DEFAULT_STRATEGY_TICK_SIZE = 0.1;

export function priceDistanceToTicks(distance: number, tickSize: number): number {
  if (!Number.isFinite(distance) || tickSize <= 0) return 0;
  return distance / tickSize;
}

export function structuralSlTicks(entry: number, sl: number, tickSize: number): number {
  return priceDistanceToTicks(Math.abs(entry - sl), tickSize);
}

export function journalSizingSlTicks(structuralSlTicks: number, journalSizingSlTicksCfg: number): number {
  if (journalSizingSlTicksCfg > 0) return journalSizingSlTicksCfg;
  return structuralSlTicks > 0 ? structuralSlTicks : 0;
}

export function normalizeOrderPrices(
  entry: number,
  sl: number | null,
  tp: number | null,
  exchangeTickSize: number,
): { entry: number; sl: number | null; tp: number | null } {
  return {
    entry: roundToTickSize(entry, exchangeTickSize),
    sl: sl != null ? roundToTickSize(sl, exchangeTickSize) : null,
    tp: tp != null ? roundToTickSize(tp, exchangeTickSize) : null,
  };
}

export function usdPerTickForQty(quantity: number, tickSize: number): number {
  return quantity * tickSize;
}

export function verifyRiskPct(
  equity: number,
  targetRiskPct: number,
  entry: number,
  sl: number,
  quantity: number,
  tolerancePct = 0.5,
): { ok: boolean; actualRiskPct: number; targetRiskUsd: number; actualRiskUsd: number } {
  const targetRiskUsd = equity * (targetRiskPct / 100);
  const actualRiskUsd = quantity * Math.abs(entry - sl);
  const actualRiskPct = equity > 0 ? (actualRiskUsd / equity) * 100 : 0;
  return {
    ok: Math.abs(actualRiskPct - targetRiskPct) <= tolerancePct,
    actualRiskPct,
    targetRiskUsd,
    actualRiskUsd,
  };
}

export function contractQuantityFromRisk(
  equity: number,
  riskPct: number,
  entry: number,
  sl: number,
  spec: Pick<SymbolSpec, 'stepSize' | 'minQty' | 'maxQty'>,
): { riskUsd: number; quantity: number; priceDistance: number } {
  const riskUsd = equity * (riskPct / 100);
  const priceDistance = Math.abs(entry - sl);
  const quantity = quantityFromRiskUsd(riskUsd, entry, sl, spec);
  return { riskUsd, quantity, priceDistance };
}
