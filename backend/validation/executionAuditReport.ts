import type {
  DriftMetrics,
  ExecutionAuditScores,
  LivePeriodStats,
  SimBaseline30d,
  ValidationAlert,
} from './types';

export function brokerExecutionQualityScore(live: LivePeriodStats): number {
  let score = 100;
  if (live.avgSlippagePips > 2) score -= (live.avgSlippagePips - 2) * 12;
  if (live.maxSlippagePips > 4) score -= 15;
  if (live.avgSpreadPips > 5) score -= (live.avgSpreadPips - 3) * 8;
  if (live.avgLatencyMs > 800) score -= 10;
  if (live.avgLatencyMs > 2000) score -= 15;
  const rejectRate = live.rejectedOrders / Math.max(1, live.trades + live.rejectedOrders);
  score -= rejectRate * 80;
  const missRate = live.missedTrades / Math.max(1, live.trades + live.missedTrades);
  score -= missRate * 60;
  return Math.round(Math.max(0, Math.min(100, score)));
}

export function realMoneyReadinessScore(
  variancePct: number,
  brokerScore: number,
  alerts: ValidationAlert[],
  liveTrades: number
): number {
  if (liveTrades === 0) return 0;
  const criticals = alerts.filter((a) => a.severity === 'CRITICAL' && a.code !== 'LOW_SAMPLE').length;
  const v = variancePct < 0 ? 50 : variancePct;
  let score = 100 - v * 0.45 - criticals * 18;
  score = score * 0.55 + brokerScore * 0.45;
  if (liveTrades < 15) score = Math.min(score, 72);
  if (liveTrades < 8) score = Math.min(score, 58);
  return Math.round(Math.max(0, Math.min(100, score)));
}

export function recommendAccountTier(
  readiness: number,
  live: LivePeriodStats,
  alerts: ValidationAlert[]
): ExecutionAuditScores['recommendedAccountTier'] {
  if (live.trades === 0) return 'micro';
  const critical = alerts.some((a) => a.severity === 'CRITICAL' && a.code !== 'LOW_SAMPLE');
  if (critical || readiness < 55) return 'micro';
  if (readiness < 70 || live.trades < 20) return 'micro';
  if (readiness < 78) return '$1k';
  if (readiness < 85) return '$5k';
  if (readiness < 92) return '$25k';
  return 'scale_larger';
}

export function buildExecutionAuditScores(
  variancePct: number,
  live: LivePeriodStats,
  alerts: ValidationAlert[]
): ExecutionAuditScores {
  const brokerExecutionQuality = brokerExecutionQualityScore(live);
  const realMoneyReadiness = realMoneyReadinessScore(variancePct, brokerExecutionQuality, alerts, live.trades);
  return {
    simVsLiveVariancePct: variancePct,
    brokerExecutionQuality,
    realMoneyReadiness,
    recommendedAccountTier: recommendAccountTier(realMoneyReadiness, live, alerts),
  };
}

export function formatExecutionAuditReport(args: {
  generatedAt: string;
  windowDays: number;
  sim: SimBaseline30d;
  live: LivePeriodStats;
  drift: DriftMetrics;
  alerts: ValidationAlert[];
  scores: ExecutionAuditScores;
  freezeOk: boolean;
  freezeErrors: string[];
  logPath: string;
  eventCount: number;
}): string {
  const lines: string[] = [];
  lines.push('BILSHENZ — INSTITUTIONAL EXECUTION AUDIT (FORWARD DEMO)');
  lines.push(`Generated: ${args.generatedAt}`);
  lines.push(`Window: ${args.windowDays} days · Events logged: ${args.eventCount}`);
  lines.push(`Log: ${args.logPath}`);
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('0. STRATEGY FREEZE');
  lines.push('═══════════════════════════════════════════════════════════');
  if (args.freezeOk) lines.push('  Status: PASS — signal sources + config match frozen manifest');
  else {
    lines.push('  Status: FAIL — do not deploy until resolved');
    for (const e of args.freezeErrors) lines.push(`  • ${e}`);
  }
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('1. SIMULATED BASELINE (frozen config, MT5 feed)');
  lines.push('═══════════════════════════════════════════════════════════');
  lines.push(`  Return: ${args.sim.netPct >= 0 ? '+' : ''}${args.sim.netPct.toFixed(1)}% · Trades: ${args.sim.trades}`);
  lines.push(`  WR: ${args.sim.winRatePct.toFixed(1)}% · PF: ${args.sim.profitFactor.toFixed(2)} · Max DD: $${args.sim.maxDrawdownUsd.toFixed(0)}`);
  lines.push(`  Friction: ${args.sim.spreadPips.toFixed(2)}p spread · ${args.sim.slippagePipsPerSide.toFixed(2)}p slip/side`);
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('2. LIVE FORWARD DEMO LOG');
  lines.push('═══════════════════════════════════════════════════════════');
  lines.push(`  Fills: ${args.live.trades} · WR: ${args.live.winRatePct.toFixed(1)}% · PF: ${args.live.profitFactor.toFixed(2)}`);
  lines.push(`  Net PnL: $${args.live.netPnlUsd.toFixed(2)} · Equity: $${args.live.startEquity.toFixed(0)} → $${args.live.endEquity.toFixed(0)}`);
  lines.push(`  Max DD: $${args.live.maxDrawdownUsd.toFixed(0)}`);
  lines.push(`  Avg slippage: ${args.live.avgSlippagePips.toFixed(2)}p · Avg spread: ${args.live.avgSpreadPips.toFixed(2)}p · Avg latency: ${args.live.avgLatencyMs.toFixed(0)}ms`);
  lines.push(`  Rejected: ${args.live.rejectedOrders} · Missed: ${args.live.missedTrades} · Mismatches: ${args.live.executionMismatches}`);
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('3. DRIFT vs SIMULATION');
  lines.push('═══════════════════════════════════════════════════════════');
  lines.push(`  Win-rate drift: ${args.drift.winRateDriftPct >= 0 ? '+' : ''}${args.drift.winRateDriftPct.toFixed(1)}%`);
  lines.push(`  PF drift: ${args.drift.pfDriftPct >= 0 ? '+' : ''}${args.drift.pfDriftPct.toFixed(1)}%`);
  lines.push(`  Slippage vs sim assumption: ${args.drift.slippageVsSimPips >= 0 ? '+' : ''}${args.drift.slippageVsSimPips.toFixed(2)}p`);
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('4. ALERTS');
  lines.push('═══════════════════════════════════════════════════════════');
  for (const a of args.alerts) {
    lines.push(`  [${a.severity}] ${a.code}: ${a.message}`);
  }
  lines.push('');

  lines.push('═══════════════════════════════════════════════════════════');
  lines.push('A. SIMULATION vs LIVE VARIANCE %');
  lines.push('═══════════════════════════════════════════════════════════');
  if (args.scores.simVsLiveVariancePct < 0) {
    lines.push('  N/A — no live forward-demo fills yet (run 30d AUTO-EXEC on demo)');
  } else {
    lines.push(`  ${args.scores.simVsLiveVariancePct.toFixed(1)}% (lower = better alignment)`);
  }
  lines.push('');

  lines.push('B. BROKER EXECUTION QUALITY SCORE');
  lines.push('═══════════════════════════════════════════════════════════');
  lines.push(`  ${args.scores.brokerExecutionQuality}/100`);
  lines.push('');

  lines.push('C. REAL-MONEY READINESS SCORE');
  lines.push('═══════════════════════════════════════════════════════════');
  lines.push(`  ${args.scores.realMoneyReadiness}/100`);
  lines.push('');

  lines.push('D. RECOMMENDED ACCOUNT SIZE');
  lines.push('═══════════════════════════════════════════════════════════');
  const tier = args.scores.recommendedAccountTier;
  const tierNote: Record<string, string> = {
    micro: 'Micro — $200–500, 0.25–0.5% risk, 30+ more demo days',
    '$1k': '$1k — 0.5% risk, cap 2 trades/day after 30d forward pass',
    '$5k': '$5k — 0.5–0.75% risk after 60d stable execution',
    '$25k': '$25k — scale after 90d forward + slippage within sim band',
    scale_larger: 'Scale larger — readiness high; still cap daily risk 3%',
  };
  lines.push(`  ${tier}: ${tierNote[tier] ?? tier}`);
  lines.push('');

  return lines.join('\n');
}
