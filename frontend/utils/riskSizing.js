import { SIM_DESK_EQUITY, DISPLAY_PIP_SIZE } from '../security/deskConstants';

export { SIM_DESK_EQUITY };

/**
 * Prefer equity, then balance (MT5 account snapshot).
 * @param {{ balance?: number, equity?: number } | null | undefined} account
 */
export function resolveAccountEquity(account, fallback = SIM_DESK_EQUITY) {
  if (!account) return fallback;
  if (Number.isFinite(account.equity) && account.equity > 0) return account.equity;
  if (Number.isFinite(account.balance) && account.balance > 0) return account.balance;
  return fallback;
}

/** Chart / broker stop distance in pips (entry → structural SL). */
export function structuralSlPipsFromTrade(trade, pip) {
  if (trade?.entry == null || trade?.sl == null) return 0;
  const p = pip > 0 ? pip : DISPLAY_PIP_SIZE;
  return Math.abs(trade.entry - trade.sl) / p;
}

/**
 * Pips used for lot sizing — fixed journal distance when set, else structural.
 * Matches backtest `journalSizingSlPips` (structural SL still sent to broker).
 */
export function journalSizingSlPips(structuralSlPips, cfg) {
  const fixed = cfg?.journalSizingSlPips ?? 0;
  if (fixed > 0) return fixed;
  return structuralSlPips > 0 ? structuralSlPips : 0;
}

/**
 * Risk $ and lot size from balance × risk% ÷ (SL pips × $/pip/lot).
 * @param {{ equity: number, riskPct: number, slPips: number, usdPerPipPerLot?: number, minLot?: number, lotStep?: number, maxLot?: number }} p
 */
export function computeRiskSizing(p) {
  const eq = p.equity > 0 && Number.isFinite(p.equity) ? p.equity : SIM_DESK_EQUITY;
  const pct = p.riskPct > 0 && Number.isFinite(p.riskPct) ? p.riskPct : 1;
  const riskUsd = eq * (pct / 100);
  const slPips = p.slPips > 0 && Number.isFinite(p.slPips) ? p.slPips : 0;
  const pipUsd =
    p.usdPerPipPerLot != null && p.usdPerPipPerLot > 0
      ? p.usdPerPipPerLot
      : 12.5;
  const minLot = p.minLot ?? 0.01;
  const lotStep = p.lotStep ?? 0.01;
  const maxLot = p.maxLot ?? 50;

  let lots = 0;
  if (slPips > 0) {
    lots = riskUsd / (slPips * pipUsd);
    lots = Math.floor(lots / lotStep + 1e-9) * lotStep;
    if (lots > 0 && lots < minLot) lots = minLot;
    lots = Math.min(maxLot, lots);
  }

  return { equity: eq, riskPct: pct, riskUsd, lots, slPips, usdPerPipPerLot: pipUsd };
}

/**
 * Live / auto-exec sizing: 1% (or tier) risk on journal SL pips; chart SL unchanged on order.
 * @param {{ side?: string, entry?: number | null, sl?: number | null, tp1?: number | null }} trade
 */
export function sizingForTrade(trade, cfg, equity, riskPct) {
  const pip = cfg?.pipSize ?? DISPLAY_PIP_SIZE;
  const structuralSlPips = structuralSlPipsFromTrade(trade, pip);
  const sizingSlPips = journalSizingSlPips(structuralSlPips, cfg);
  const base = computeRiskSizing({
    equity,
    riskPct,
    slPips: sizingSlPips,
    usdPerPipPerLot: cfg?.simUsdPerEnginePip ?? 12.5,
  });
  let rewardUsd = 0;
  if (trade?.tp1 != null && Number.isFinite(trade.tp1) && trade.entry != null && sizingSlPips > 0) {
    const tpPips = Math.abs(trade.tp1 - trade.entry) / pip;
    rewardUsd = base.riskUsd * (tpPips / sizingSlPips);
  }
  return { ...base, structuralSlPips, sizingSlPips, rewardUsd };
}

/**
 * @param {{ side?: string, entry?: number | null, sl?: number | null }} trade
 */
export function lotsForTrade(trade, cfg, equity, riskPct) {
  const s = sizingForTrade(trade, cfg, equity, riskPct);
  return s.lots > 0 ? s.lots : 0.01;
}

/** Closed journal P&L in USD — same model as 12mo backtest (`journalSizingSlPips`). */
export function journalClosedUsd(rows, cfg, equity, riskPct) {
  const pip = cfg?.pipSize ?? DISPLAY_PIP_SIZE;
  const pipUsd = cfg?.simUsdPerEnginePip ?? 12.5;
  let total = 0;
  for (const r of rows) {
    if (!r?.out || r.entry == null || r.sl == null) continue;
    const structural = Math.abs(r.entry - r.sl) / pip;
    if (structural <= 0) continue;
    const sizingSl = journalSizingSlPips(structural, cfg);
    const { riskUsd, lots } = computeRiskSizing({ equity, riskPct, slPips: sizingSl, usdPerPipPerLot: pipUsd });
    if (r.out === 'LOSS') {
      total -= riskUsd;
    } else if (r.out === 'HALF_LOSS') {
      total -= riskUsd * 0.5;
    } else if (r.out === 'WIN' && r.tp1 != null && Number.isFinite(r.tp1)) {
      const tpPips = Math.abs(r.tp1 - r.entry) / pip;
      total += tpPips * pipUsd * lots;
    }
  }
  return total;
}

export function fmtRiskUsd(amount) {
  const n = Math.round(amount);
  return `$${n.toLocaleString('en-US')}`;
}

export function pctOfBalanceLabel(pct, equity, mt5Live) {
  const riskUsd = equity * (pct / 100);
  const bal = `$${Math.round(equity).toLocaleString('en-US')}`;
  return mt5Live ? `${pct.toFixed(2)}% (${fmtRiskUsd(riskUsd)} of ${bal})` : `${pct.toFixed(2)}% (${fmtRiskUsd(riskUsd)} of $50k sim)`;
}

/** Lot-size subtitle for UI when journal sizing differs from chart SL. */
export function lotSizeSubtitle(riskUsd, structuralSlPips, sizingSlPips, simUsdPerPip, cfg) {
  const fixed = cfg?.journalSizingSlPips ?? 0;
  if (fixed > 0 && structuralSlPips > sizingSlPips + 0.05) {
    return `$${Math.round(riskUsd)} ÷ ${sizingSlPips}p risk (${structuralSlPips.toFixed(1)}p chart SL) ÷ $${simUsdPerPip}/pip`;
  }
  return `$${Math.round(riskUsd)} ÷ ${structuralSlPips > 0 ? structuralSlPips.toFixed(1) : '—'}p SL ÷ $${simUsdPerPip}/pip`;
}
