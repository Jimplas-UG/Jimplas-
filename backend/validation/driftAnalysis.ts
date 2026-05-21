import type { DriftMetrics, ForwardDemoEvent, LivePeriodStats, SimBaseline30d } from './types';

const PIP = 0.1;

function pf(grossProfit: number, grossLoss: number): number {
  return grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 99 : 0;
}

/** Aggregate live forward-demo log into period stats (fills + equity snapshots). */
export function liveStatsFromEvents(events: ForwardDemoEvent[], startEquity = 1000): LivePeriodStats {
  const fills = events.filter((e) => e.type === 'ORDER_FILL');
  const equities = events.filter((e) => e.type === 'EQUITY_SNAPSHOT' && e.equityUsd != null);
  const rejected = events.filter((e) => e.type === 'ORDER_REJECTED').length;
  const missed = events.filter((e) => e.type === 'MISSED_TRADE').length;
  const mismatches = events.filter((e) => e.type === 'EXECUTION_MISMATCH').length;

  let grossProfit = 0;
  let grossLoss = 0;
  let wins = 0;
  let losses = 0;

  for (const f of fills) {
    const slipUsd = (f.slippagePips ?? 0) * PIP * 10;
    if (slipUsd <= 0) {
      wins++;
      grossProfit += Math.abs(slipUsd) + 20;
    } else {
      losses++;
      grossLoss += Math.abs(slipUsd) + 20;
    }
  }

  const startEq = equities[0]?.equityUsd ?? startEquity;
  const endEq = equities[equities.length - 1]?.equityUsd ?? startEq;
  let peak = startEq;
  let maxDd = 0;
  for (const e of equities) {
    const eq = e.equityUsd!;
    if (eq > peak) peak = eq;
    maxDd = Math.max(maxDd, peak - eq);
  }

  const slips = fills.map((f) => f.slippagePips ?? 0);
  const spreads = fills.map((f) => f.spreadAtExecutionPips ?? 0).filter((x) => x > 0);
  const latencies = fills.map((f) => f.latencyMs ?? 0).filter((x) => x > 0);

  const trades = fills.length;
  const winRatePct = trades > 0 ? (wins / trades) * 100 : 0;

  return {
    trades,
    wins,
    losses,
    winRatePct,
    profitFactor: pf(grossProfit, grossLoss),
    grossProfit,
    grossLoss,
    netPnlUsd: endEq - startEq,
    startEquity: startEq,
    endEquity: endEq,
    maxDrawdownUsd: maxDd,
    avgSlippagePips: slips.length ? slips.reduce((a, b) => a + b, 0) / slips.length : 0,
    maxSlippagePips: slips.length ? Math.max(...slips) : 0,
    avgSpreadPips: spreads.length ? spreads.reduce((a, b) => a + b, 0) / spreads.length : 0,
    avgLatencyMs: latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : 0,
    rejectedOrders: rejected,
    missedTrades: missed,
    executionMismatches: mismatches,
  };
}

export function computeDrift(sim: SimBaseline30d, live: LivePeriodStats): DriftMetrics {
  const winRateDriftPct = live.winRatePct - sim.winRatePct;
  const pfDriftPct = sim.profitFactor > 0 ? ((live.profitFactor - sim.profitFactor) / sim.profitFactor) * 100 : 0;
  const simDaily = sim.netPct / sim.windowDays;
  const liveDaily = live.startEquity > 0 ? (live.netPnlUsd / live.startEquity / Math.max(1, live.trades)) * 100 * 30 : 0;
  const returnDriftPct = liveDaily - simDaily * 30;
  const tradeCountDriftPct =
    sim.trades > 0 ? ((live.trades - sim.trades) / sim.trades) * 100 : live.trades > 0 ? 100 : 0;
  const slippageVsSimPips = live.avgSlippagePips - sim.slippagePipsPerSide * 2;
  return {
    winRateDriftPct,
    pfDriftPct,
    returnDriftPct,
    tradeCountDriftPct,
    slippageVsSimPips,
  };
}

/** Overall simulation vs live variance (0–100+, lower is better alignment). */
export function simVsLiveVariancePct(drift: DriftMetrics, sim: SimBaseline30d, live: LivePeriodStats): number {
  const wr = Math.abs(drift.winRateDriftPct);
  const pf = Math.abs(drift.pfDriftPct);
  const ret = Math.abs(drift.returnDriftPct);
  const slip = Math.abs(drift.slippageVsSimPips) * 8;
  const exec =
    (live.rejectedOrders + live.missedTrades + live.executionMismatches) /
    Math.max(1, live.trades + live.rejectedOrders) *
    100;
  const raw = wr * 1.2 + pf * 0.4 + Math.min(40, ret) + slip + exec;
  if (live.trades === 0) return -1;
  const cap = raw;
  return Math.round(Math.min(100, cap) * 10) / 10;
}
