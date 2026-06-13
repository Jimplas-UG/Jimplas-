/**
 * Binance Futures tick units — execution/risk boundary.
 * Engine snapshots may still use *Pips field names (frozen strategy).
 */
import { isBinanceBroker } from './brokerMode';

export const DEFAULT_STRATEGY_TICK_SIZE = 0.1;

export function engineTickSize(cfg) {
  return cfg?.tickSize ?? cfg?.pipSize ?? DEFAULT_STRATEGY_TICK_SIZE;
}

export function structuralSlTicksFromTrade(trade, tickSize) {
  if (trade?.entry == null || trade?.sl == null) return 0;
  const t = tickSize > 0 ? tickSize : DEFAULT_STRATEGY_TICK_SIZE;
  return Math.abs(trade.entry - trade.sl) / t;
}

export function journalSizingSlTicks(structuralSlTicks, cfg) {
  const fixed = cfg?.journalSizingSlTicks ?? cfg?.journalSizingSlPips ?? 0;
  if (fixed > 0) return fixed;
  return structuralSlTicks > 0 ? structuralSlTicks : 0;
}

export function roundToTickSize(price, tickSize) {
  if (!Number.isFinite(price) || !tickSize || tickSize <= 0) return price;
  const precision = Math.max(0, Math.ceil(-Math.log10(tickSize)));
  const rounded = Math.floor(price / tickSize + 1e-9) * tickSize;
  return Number(rounded.toFixed(precision));
}

export function roundToStepSize(qty, stepSize) {
  if (!Number.isFinite(qty) || !stepSize || stepSize <= 0) return qty;
  const precision = Math.max(0, Math.ceil(-Math.log10(stepSize)));
  const rounded = Math.floor(qty / stepSize + 1e-9) * stepSize;
  return Number(rounded.toFixed(precision));
}

export function contractQuantityFromRisk(riskUsd, entry, sl, spec) {
  const dist = Math.abs(entry - sl);
  if (dist <= 0 || riskUsd <= 0 || !spec) return 0;
  let qty = riskUsd / dist;
  const step = spec.stepSize ?? 0.001;
  const minQty = spec.minQty ?? step;
  qty = roundToStepSize(qty, step);
  if (qty > 0 && qty < minQty) qty = minQty;
  if (spec.maxQty && qty > spec.maxQty) qty = spec.maxQty;
  return qty;
}

export function verifyRiskPct(equity, targetRiskPct, entry, sl, quantity, tolerancePct = 0.5) {
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

export function positionSizeLabel() {
  return isBinanceBroker() ? 'Contract Qty' : 'Lot Size';
}

export function distanceUnit() {
  return isBinanceBroker() ? 'tick' : 'pip';
}

export function fmtDistance(n, decimals = 1) {
  if (n == null || !Number.isFinite(n)) return '—';
  const u = distanceUnit();
  return `${Number(n).toFixed(decimals)} ${u}${Number(n) === 1 ? '' : 's'}`;
}

/** @deprecated */
export const structuralSlPipsFromTrade = structuralSlTicksFromTrade;
