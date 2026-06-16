import { SIM_DESK_EQUITY, DISPLAY_TICK_SIZE } from '../security/deskConstants';
import {
  engineTickSize,
  roundToStepSize,
  structuralSlTicksFromTrade,
  journalSizingSlTicks,
  verifyRiskPct,
} from '../lib/tickUnits';
import { contractSizeSubtitle } from '../lib/tickDisplay';

export { SIM_DESK_EQUITY, verifyRiskPct, contractSizeSubtitle, contractSizeSubtitle as lotSizeSubtitle };
export { structuralSlTicksFromTrade, journalSizingSlTicks };
export const DISPLAY_PIP_SIZE = DISPLAY_TICK_SIZE;
export const structuralSlPipsFromTrade = structuralSlTicksFromTrade;
export const journalSizingSlPips = journalSizingSlTicks;

export function resolveAccountEquity(account, fallback = SIM_DESK_EQUITY) {
  if (!account) return fallback;
  if (Number.isFinite(account.equity) && account.equity > 0) return account.equity;
  if (Number.isFinite(account.balance) && account.balance > 0) return account.balance;
  return fallback;
}

export function computeRiskSizing(p) {
  const eq = p.equity > 0 && Number.isFinite(p.equity) ? p.equity : SIM_DESK_EQUITY;
  const pct = p.riskPct > 0 && Number.isFinite(p.riskPct) ? p.riskPct : 1;
  const riskUsd = eq * (pct / 100);
  const slTicks = p.slTicks ?? p.slPips ?? 0;
  const slN = slTicks > 0 && Number.isFinite(slTicks) ? slTicks : 0;
  const tickUsd = p.usdPerTick ?? p.usdPerPipPerLot ?? 12.5;
  const minLot = p.minLot ?? 0.01;
  const lotStep = p.lotStep ?? 0.01;
  const maxLot = p.maxLot ?? 50;
  let lots = 0;
  if (slN > 0) {
    lots = riskUsd / (slN * tickUsd);
    lots = Math.floor(lots / lotStep + 1e-9) * lotStep;
    if (lots > 0 && lots < minLot) lots = minLot;
    lots = Math.min(maxLot, lots);
  }
  return {
    equity: eq,
    riskPct: pct,
    riskUsd,
    lots,
    slTicks: slN,
    slPips: slN,
    usdPerTick: tickUsd,
    usdPerPipPerLot: tickUsd,
  };
}

export function sizingForTrade(trade, cfg, equity, riskPct) {
  const tick = engineTickSize(cfg);
  const structuralSlTicks = structuralSlTicksFromTrade(trade, tick);
  const sizingSlTicks = journalSizingSlTicks(structuralSlTicks, cfg);
  const base = computeRiskSizing({
    equity,
    riskPct,
    slTicks: sizingSlTicks,
    usdPerTick: cfg?.simUsdPerEngineTick ?? cfg?.simUsdPerEnginePip ?? 12.5,
  });
  let rewardUsd = 0;
  if (trade?.tp1 != null && trade.entry != null && sizingSlTicks > 0) {
    const tpTicks = Math.abs(trade.tp1 - trade.entry) / tick;
    rewardUsd = base.riskUsd * (tpTicks / sizingSlTicks);
  }
  return {
    ...base,
    structuralSlTicks,
    sizingSlTicks,
    structuralSlPips: structuralSlTicks,
    sizingSlPips: sizingSlTicks,
    rewardUsd,
  };
}

export function quantityForTrade(trade, cfg, equity, riskPct, spec) {
  const tick = engineTickSize(cfg);
  const structuralSlTicks = structuralSlTicksFromTrade(trade, tick);
  const sizingSlTicks = journalSizingSlTicks(structuralSlTicks, cfg);
  const base = computeRiskSizing({
    equity,
    riskPct,
    slTicks: sizingSlTicks,
    usdPerTick: cfg?.simUsdPerEngineTick ?? cfg?.simUsdPerEnginePip ?? 12.5,
  });
  if (!spec || trade?.entry == null || trade?.sl == null) {
    return { ...base, quantity: base.lots, structuralSlTicks, sizingSlTicks, structuralSlPips: structuralSlTicks, sizingSlPips: sizingSlTicks };
  }
  let qty = base.riskUsd / Math.abs(trade.entry - trade.sl);
  qty = roundToStepSize(qty, spec.stepSize ?? 0.001);
  const minQty = spec.minQty ?? spec.stepSize ?? 0.001;
  if (qty > 0 && qty < minQty) qty = minQty;
  return { ...base, quantity: qty, structuralSlTicks, sizingSlTicks, structuralSlPips: structuralSlTicks, sizingSlPips: sizingSlTicks };
}

export function lotsForTrade(trade, cfg, equity, riskPct) {
  const s = sizingForTrade(trade, cfg, equity, riskPct);
  return s.lots > 0 ? s.lots : 0.01;
}

export function journalClosedUsd(rows, cfg, equity, riskPct) {
  const tick = engineTickSize(cfg);
  const tickUsd = cfg?.simUsdPerEngineTick ?? cfg?.simUsdPerEnginePip ?? 12.5;
  let total = 0;
  for (const r of rows) {
    if (!r?.out || r.entry == null || r.sl == null) continue;
    const structural = Math.abs(r.entry - r.sl) / tick;
    if (structural <= 0) continue;
    const sizingSl = journalSizingSlTicks(structural, cfg);
    const { riskUsd, lots } = computeRiskSizing({ equity, riskPct, slTicks: sizingSl, usdPerTick: tickUsd });
    if (r.out === 'LOSS') total -= riskUsd;
    else if (r.out === 'HALF_LOSS') total -= riskUsd * 0.5;
    else if (r.out === 'WIN' && r.tp1 != null) {
      total += (Math.abs(r.tp1 - r.entry) / tick) * tickUsd * lots;
    }
  }
  return total;
}

export function fmtRiskUsd(amount) {
  return `$${Math.round(amount).toLocaleString('en-US')}`;
}

export function pctOfBalanceLabel(pct, equity, brokerLive) {
  const riskUsd = equity * (pct / 100);
  const bal = `$${Math.round(equity).toLocaleString('en-US')}`;
  return brokerLive ? `${pct.toFixed(2)}% (${fmtRiskUsd(riskUsd)} of ${bal})` : `${pct.toFixed(2)}% (${fmtRiskUsd(riskUsd)} of $50k sim)`;
}
