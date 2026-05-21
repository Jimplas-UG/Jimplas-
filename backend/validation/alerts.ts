import type { DriftMetrics, LivePeriodStats, SimBaseline30d, ValidationAlert } from './types';

export type AlertThresholds = {
  maxWinRateDriftPct: number;
  minProfitFactor: number;
  maxDrawdownUsd: number;
  maxAvgSlippagePips: number;
  maxExecutionMismatchRatePct: number;
};

export const DEFAULT_ALERT_THRESHOLDS: AlertThresholds = {
  maxWinRateDriftPct: 10,
  minProfitFactor: 1.8,
  maxDrawdownUsd: 400,
  maxAvgSlippagePips: 2.5,
  maxExecutionMismatchRatePct: 15,
};

export function evaluateValidationAlerts(
  sim: SimBaseline30d,
  live: LivePeriodStats,
  drift: DriftMetrics,
  thresholds: AlertThresholds = DEFAULT_ALERT_THRESHOLDS
): ValidationAlert[] {
  const alerts: ValidationAlert[] = [];

  if (Math.abs(drift.winRateDriftPct) > thresholds.maxWinRateDriftPct) {
    alerts.push({
      code: 'WIN_RATE_DRIFT',
      severity: 'CRITICAL',
      message: `Win rate deviates ${drift.winRateDriftPct.toFixed(1)}% from sim (limit ±${thresholds.maxWinRateDriftPct}%)`,
      value: drift.winRateDriftPct,
      threshold: thresholds.maxWinRateDriftPct,
    });
  }

  if (live.trades >= 5 && live.profitFactor < thresholds.minProfitFactor) {
    alerts.push({
      code: 'PF_BELOW_FLOOR',
      severity: 'CRITICAL',
      message: `Profit factor ${live.profitFactor.toFixed(2)} below ${thresholds.minProfitFactor}`,
      value: live.profitFactor,
      threshold: thresholds.minProfitFactor,
    });
  }

  const ddLimit = Math.max(thresholds.maxDrawdownUsd, sim.maxDrawdownUsd * 1.35);
  if (live.maxDrawdownUsd > ddLimit) {
    alerts.push({
      code: 'DD_EXCEEDED',
      severity: 'CRITICAL',
      message: `Drawdown $${live.maxDrawdownUsd.toFixed(0)} exceeds tolerance $${ddLimit.toFixed(0)}`,
      value: live.maxDrawdownUsd,
      threshold: ddLimit,
    });
  }

  if (live.avgSlippagePips > thresholds.maxAvgSlippagePips) {
    alerts.push({
      code: 'SLIPPAGE_HIGH',
      severity: 'WARN',
      message: `Avg slippage ${live.avgSlippagePips.toFixed(2)}p > ${thresholds.maxAvgSlippagePips}p`,
      value: live.avgSlippagePips,
      threshold: thresholds.maxAvgSlippagePips,
    });
  }

  const mismatchRate =
    ((live.rejectedOrders + live.missedTrades + live.executionMismatches) /
      Math.max(1, live.trades + live.rejectedOrders + live.missedTrades)) *
    100;
  if (mismatchRate > thresholds.maxExecutionMismatchRatePct) {
    alerts.push({
      code: 'EXECUTION_MISMATCH',
      severity: 'CRITICAL',
      message: `Execution mismatch rate ${mismatchRate.toFixed(1)}% > ${thresholds.maxExecutionMismatchRatePct}%`,
      value: mismatchRate,
      threshold: thresholds.maxExecutionMismatchRatePct,
    });
  }

  if (live.trades < Math.max(3, sim.trades * 0.25) && sim.trades >= 10) {
    alerts.push({
      code: 'LOW_SAMPLE',
      severity: 'WARN',
      message: `Only ${live.trades} live fills vs ~${sim.trades} sim trades — extend forward demo`,
      value: live.trades,
    });
  }

  if (alerts.length === 0) {
    alerts.push({
      code: 'OK',
      severity: 'INFO',
      message: 'No threshold breaches in current forward-demo window',
    });
  }

  return alerts;
}
