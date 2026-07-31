export const STORAGE_RISK_DESK = '@bilshenz_v1/riskDeskConfig';

/** Fixed partition tiers — amount you subscribe / are ready to lose. */
export const PARTITION_PRESETS_USD = [50, 100, 200, 500];

/** Fixed institutional leverage per leg — primary short 5x, recovery longs 10x. */
export const LEG_LEVERAGE_POLICY = { short: 5, long1: 10, long2: 10 };

/** @deprecated — leverage is fixed per leg; kept for legacy config reads only. */
export const LEVERAGE_PRESETS = [5, 10];

/** Margin mode toggles. */
export const MARGIN_MODE_PRESETS = ['ISOLATED', 'CROSS'];

/** Capital & risk desk — independent from strategy signal logic. */
export const RISK_DESK_DEFAULTS = {
  partitionUsd: 100,
  partitionLocked: false,
  shortPartitionPct: 50,
  long1PartitionPct: 40,
  long2PartitionPct: 40,
  riskPerTradePct: 1,
  maxDailyLossPct: 3,
  maxWeeklyLossPct: 8,
  maxDrawdownPct: 15,
  maxOpenPositions: 5,
  maxExposurePerAssetPct: 25,
  maxPortfolioExposurePct: 60,
  defaultLeverage: LEG_LEVERAGE_POLICY.short,
  maxAllowedLeverage: LEG_LEVERAGE_POLICY.long1,
  marginMode: 'ISOLATED',
  emergencyStop: false,
  pauseNewTrades: false,
  autoStopDailyLoss: true,
  autoStopDrawdown: true,
  autoStopApiErrors: false,
  peakEquity: null,
  apiErrorStreak: 0,
};

function snapPartitionUsd(v) {
  const n = Math.round(Number(v));
  if (PARTITION_PRESETS_USD.includes(n)) return n;
  return PARTITION_PRESETS_USD.reduce(
    (best, p) => (Math.abs(p - n) < Math.abs(best - n) ? p : best),
    RISK_DESK_DEFAULTS.partitionUsd,
  );
}

function snapLeverage(v) {
  const n = Math.round(Number(v));
  if (LEVERAGE_PRESETS.includes(n)) return n;
  return LEVERAGE_PRESETS.reduce(
    (best, p) => (Math.abs(p - n) < Math.abs(best - n) ? p : best),
    RISK_DESK_DEFAULTS.defaultLeverage,
  );
}

export function normalizeRiskDeskConfig(raw) {
  const d = RISK_DESK_DEFAULTS;
  const n = (k, min, max) => {
    const v = Number(raw?.[k]);
    if (!Number.isFinite(v)) return d[k];
    return Math.min(max, Math.max(min, v));
  };

  let partitionUsd = snapPartitionUsd(raw?.partitionUsd);
  if (!raw?.partitionUsd && raw?.tradingPartitionPct != null) {
    partitionUsd = 100;
  }

  const defaultLeverage = LEG_LEVERAGE_POLICY.short;
  const maxAllowedLeverage = LEG_LEVERAGE_POLICY.long1;

  let shortPartitionPct = n('shortPartitionPct', 1, 100);
  let long1PartitionPct = n('long1PartitionPct', 1, 100);
  let long2PartitionPct = n('long2PartitionPct', 1, 100);
  // Migrate the long-first 12.5/12.5 clamp back to the original recovery sizing.
  if (long1PartitionPct === 12.5 && long2PartitionPct === 12.5) {
    long1PartitionPct = RISK_DESK_DEFAULTS.long1PartitionPct;
    long2PartitionPct = RISK_DESK_DEFAULTS.long2PartitionPct;
  }
  if (shortPartitionPct < 1) shortPartitionPct = RISK_DESK_DEFAULTS.shortPartitionPct;

  return {
    partitionUsd,
    partitionLocked: !!raw?.partitionLocked,
    shortPartitionPct,
    long1PartitionPct,
    long2PartitionPct,
    riskPerTradePct: n('riskPerTradePct', 0.1, 5),
    maxDailyLossPct: n('maxDailyLossPct', 0.5, 25),
    maxWeeklyLossPct: n('maxWeeklyLossPct', 1, 40),
    maxDrawdownPct: n('maxDrawdownPct', 1, 50),
    maxOpenPositions: Math.max(2, Math.round(n('maxOpenPositions', 2, 20))),
    maxExposurePerAssetPct: n('maxExposurePerAssetPct', 5, 100),
    maxPortfolioExposurePct: n('maxPortfolioExposurePct', 10, 100),
    defaultLeverage,
    maxAllowedLeverage,
    marginMode: 'ISOLATED',
    emergencyStop: !!raw?.emergencyStop,
    pauseNewTrades: !!raw?.pauseNewTrades,
    autoStopDailyLoss: raw?.autoStopDailyLoss !== false,
    autoStopDrawdown: raw?.autoStopDrawdown !== false,
    autoStopApiErrors: false,
    peakEquity: Number.isFinite(raw?.peakEquity) ? raw.peakEquity : null,
    apiErrorStreak: Math.max(0, Math.round(n('apiErrorStreak', 0, 99))),
  };
}
