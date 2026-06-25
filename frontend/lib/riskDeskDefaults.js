export const STORAGE_RISK_DESK = '@bilshenz_v1/riskDeskConfig';

/** Fixed partition tiers — amount you subscribe / are ready to lose. */
export const PARTITION_PRESETS_USD = [50, 100, 200, 500];

/** Leverage toggles. */
export const LEVERAGE_PRESETS = [3, 5, 10, 20];

/** Margin mode toggles. */
export const MARGIN_MODE_PRESETS = ['ISOLATED', 'CROSS'];

/** Capital & risk desk — independent from strategy signal logic. */
export const RISK_DESK_DEFAULTS = {
  partitionUsd: 100,
  riskPerTradePct: 1,
  maxDailyLossPct: 3,
  maxWeeklyLossPct: 8,
  maxDrawdownPct: 15,
  maxOpenPositions: 3,
  maxExposurePerAssetPct: 25,
  maxPortfolioExposurePct: 60,
  defaultLeverage: 5,
  maxAllowedLeverage: 5,
  marginMode: 'ISOLATED',
  emergencyStop: false,
  pauseNewTrades: false,
  autoStopDailyLoss: true,
  autoStopDrawdown: true,
  autoStopApiErrors: true,
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

  const defaultLeverage = snapLeverage(raw?.defaultLeverage ?? raw?.maxAllowedLeverage ?? d.defaultLeverage);

  return {
    partitionUsd,
    riskPerTradePct: n('riskPerTradePct', 0.1, 5),
    maxDailyLossPct: n('maxDailyLossPct', 0.5, 25),
    maxWeeklyLossPct: n('maxWeeklyLossPct', 1, 40),
    maxDrawdownPct: n('maxDrawdownPct', 1, 50),
    maxOpenPositions: Math.round(n('maxOpenPositions', 1, 20)),
    maxExposurePerAssetPct: n('maxExposurePerAssetPct', 5, 100),
    maxPortfolioExposurePct: n('maxPortfolioExposurePct', 10, 100),
    defaultLeverage,
    maxAllowedLeverage: defaultLeverage,
    marginMode: raw?.marginMode === 'CROSS' ? 'CROSS' : 'ISOLATED',
    emergencyStop: !!raw?.emergencyStop,
    pauseNewTrades: !!raw?.pauseNewTrades,
    autoStopDailyLoss: raw?.autoStopDailyLoss !== false,
    autoStopDrawdown: raw?.autoStopDrawdown !== false,
    autoStopApiErrors: raw?.autoStopApiErrors !== false,
    peakEquity: Number.isFinite(raw?.peakEquity) ? raw.peakEquity : null,
    apiErrorStreak: Math.max(0, Math.round(n('apiErrorStreak', 0, 99))),
  };
}
