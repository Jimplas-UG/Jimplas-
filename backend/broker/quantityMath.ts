export type SymbolSpec = {
  symbol: string;
  tickSize: number;
  stepSize: number;
  minQty: number;
  maxQty: number;
  pipSize: number;
};

/** Round price to exchange tick size. */
export function roundToTickSize(price: number, tickSize: number): number {
  if (!Number.isFinite(price) || tickSize <= 0) return price;
  const precision = Math.max(0, Math.ceil(-Math.log10(tickSize)));
  const rounded = Math.floor(price / tickSize + 1e-9) * tickSize;
  return Number(rounded.toFixed(precision));
}

/** Round quantity to exchange step size (floor). */
export function roundToStepSize(qty: number, stepSize: number): number {
  if (!Number.isFinite(qty) || stepSize <= 0) return qty;
  const precision = Math.max(0, Math.ceil(-Math.log10(stepSize)));
  const rounded = Math.floor(qty / stepSize + 1e-9) * stepSize;
  return Number(rounded.toFixed(precision));
}

/**
 * USDT-M linear futures: riskUsd ≈ quantity × |entry − sl|.
 * Preserves 1% equity risk model from riskSizing.js.
 */
export function quantityFromRiskUsd(
  riskUsd: number,
  entry: number,
  sl: number,
  spec: Pick<SymbolSpec, 'stepSize' | 'minQty' | 'maxQty'>,
): number {
  const dist = Math.abs(entry - sl);
  if (dist <= 0 || riskUsd <= 0) return 0;
  let qty = riskUsd / dist;
  qty = roundToStepSize(qty, spec.stepSize);
  if (qty > 0 && qty < spec.minQty) qty = spec.minQty;
  if (qty > spec.maxQty) qty = spec.maxQty;
  return qty;
}

/** Convert MT5-style lots to Binance qty when lots represent ounces at 1:1. */
export function lotsToQuantity(lots: number, spec: Pick<SymbolSpec, 'stepSize' | 'minQty'>): number {
  let qty = roundToStepSize(lots, spec.stepSize);
  if (qty > 0 && qty < spec.minQty) qty = spec.minQty;
  return qty;
}

/** Stop distance in strategy ticks (legacy: slDistancePips). */
export function slDistanceTicks(entry: number, sl: number, tickSize: number): number {
  if (tickSize <= 0) return 0;
  return Math.abs(entry - sl) / tickSize;
}

export const slDistancePips = slDistanceTicks;
export const usdPerPipForQty = (qty: number, tickSize: number) => qty * tickSize;
