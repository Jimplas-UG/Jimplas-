import { filterBinanceDealsByRange, brokerDealsTotalPnl } from './journalHistMap';
import { PARTITION_PRESETS_USD } from './riskDeskDefaults';

export function fmtRiskUsd(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  const sign = x < 0 ? '-' : '';
  return `${sign}$${Math.abs(x).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export function computeCapitalAllocation(config, totalBalance) {
  const bal = Math.max(0, Number(totalBalance) || 0);
  const partitionCap = Math.max(0, Number(config.partitionUsd) || PARTITION_PRESETS_USD[1]);
  const tradingPartition = Math.min(partitionCap, bal);
  const protectedCapital = Math.max(0, bal - tradingPartition);
  const shortPct = Math.max(0, Number(config.shortPartitionPct) || 50);
  const long1Pct = Math.max(0, Number(config.long1PartitionPct) || 40);
  const long2Pct = Math.max(0, Number(config.long2PartitionPct) || 40);
  return {
    totalBalance: bal,
    protectedCapital,
    tradingPartition,
    tradableBase: tradingPartition,
    partitionUsd: partitionCap,
    shortLegUsd: (tradingPartition * shortPct) / 100,
    long1LegUsd: (tradingPartition * long1Pct) / 100,
    long2LegUsd: (tradingPartition * long2Pct) / 100,
    shortPartitionPct: shortPct,
    long1PartitionPct: long1Pct,
    long2PartitionPct: long2Pct,
  };
}

export function computeExposure(positions, markPrice) {
  const rows = Array.isArray(positions) ? positions : [];
  let openExposure = 0;
  let perAsset = {};
  for (const p of rows) {
    const vol = Math.abs(Number(p.volume) || 0);
    const px = Number(p.price_open) || Number(markPrice) || 0;
    const notional = vol * px;
    openExposure += notional;
    const sym = p.symbol || 'UNKNOWN';
    perAsset[sym] = (perAsset[sym] || 0) + notional;
  }
  const maxAssetExposure = Object.values(perAsset).reduce((m, v) => Math.max(m, v), 0);
  return { openExposure, maxAssetExposure, positionCount: rows.length, perAsset };
}

export function computeRiskDeskMetrics({
  config,
  totalBalance,
  brokerAccount,
  positions,
  brokerDeals,
  markPrice,
  peakEquity,
}) {
  const cap = computeCapitalAllocation(config, totalBalance);
  const usedMargin = Math.max(0, Number(brokerAccount?.margin) || 0);
  const freeMargin = Math.max(0, Number(brokerAccount?.margin_free) ?? cap.tradingPartition - usedMargin);
  const equity = Number(brokerAccount?.equity) || cap.totalBalance;
  const peak = Math.max(peakEquity ?? equity, equity);
  const drawdownPct = peak > 0 ? Math.max(0, ((peak - equity) / peak) * 100) : 0;

  const dailyDeals = filterBinanceDealsByRange(brokerDeals, 'today');
  const weeklyDeals = filterBinanceDealsByRange(brokerDeals, 'week');
  const dailyPnl = brokerDealsTotalPnl(dailyDeals);
  const weeklyPnl = brokerDealsTotalPnl(weeklyDeals);

  const dailyLossPct =
    cap.tradingPartition > 0 ? (Math.abs(Math.min(0, dailyPnl)) / cap.tradingPartition) * 100 : 0;
  const weeklyLossPct =
    cap.tradingPartition > 0 ? (Math.abs(Math.min(0, weeklyPnl)) / cap.tradingPartition) * 100 : 0;

  const { openExposure, maxAssetExposure, positionCount } = computeExposure(positions, markPrice);
  const exposurePct = cap.tradingPartition > 0 ? (openExposure / cap.tradingPartition) * 100 : 0;
  const assetExposurePct = cap.tradingPartition > 0 ? (maxAssetExposure / cap.tradingPartition) * 100 : 0;

  const availableTradingCapital = Math.max(0, cap.tradingPartition - usedMargin);
  const riskUtilizationPct =
    cap.tradingPartition > 0 ? Math.min(100, (usedMargin / cap.tradingPartition) * 100) : 0;

  const activeLeverage = Number(brokerAccount?.leverage) || config.defaultLeverage;
  const liquidationBuffer = computeLiquidationBuffer(positions, markPrice);

  const closed = (brokerDeals ?? []).filter((d) => Number(d.profit) !== 0);
  const wins = closed.filter((d) => Number(d.profit) > 0);
  const losses = closed.filter((d) => Number(d.profit) < 0);
  const winRatePct = closed.length ? (wins.length / closed.length) * 100 : null;
  const largestWin = wins.reduce((m, d) => Math.max(m, Number(d.profit)), 0);
  const largestLoss = losses.reduce((m, d) => Math.min(m, Number(d.profit)), 0);
  const avgWin = wins.length ? wins.reduce((s, d) => s + Number(d.profit), 0) / wins.length : 0;
  const avgLoss = losses.length
    ? Math.abs(losses.reduce((s, d) => s + Number(d.profit), 0) / losses.length)
    : 0;
  const avgRiskReward = avgLoss > 0 ? avgWin / avgLoss : null;

  return {
    ...cap,
    equity,
    peakEquity: peak,
    usedMargin,
    freeMargin,
    availableTradingCapital,
    openExposure,
    maxAssetExposure,
    exposurePct,
    assetExposurePct,
    positionCount,
    dailyPnl,
    weeklyPnl,
    dailyLossPct,
    weeklyLossPct,
    drawdownPct,
    riskUtilizationPct,
    activeLeverage,
    liquidationBuffer,
    winRatePct,
    avgRiskReward,
    largestWin,
    largestLoss,
    closedTrades: closed.length,
  };
}

function computeLiquidationBuffer(positions, markPrice) {
  const px = Number(markPrice);
  if (!Number.isFinite(px) || px <= 0) return null;
  const rows = Array.isArray(positions) ? positions : [];
  if (!rows.length) return null;
  let minBuf = Infinity;
  for (const p of rows) {
    const liq = Number(p.liquidationPrice);
    if (!Number.isFinite(liq) || liq <= 0) continue;
    const buf = p.type === 'BUY' ? ((px - liq) / px) * 100 : ((liq - px) / px) * 100;
    if (Number.isFinite(buf)) minBuf = Math.min(minBuf, buf);
  }
  return Number.isFinite(minBuf) ? Math.max(0, minBuf) : null;
}

/** Execution gate — does not alter strategy signals. */
export function evaluateRiskDeskGate(config, metrics, positions) {
  if (config.emergencyStop) {
    return { ok: false, reason: 'RISK_EMERGENCY_STOP' };
  }
  if (config.pauseNewTrades) {
    return { ok: false, reason: 'RISK_PAUSE_NEW_TRADES' };
  }
  if (config.autoStopApiErrors && config.apiErrorStreak >= 3) {
    return { ok: false, reason: 'RISK_API_ERRORS' };
  }
  if (config.autoStopDailyLoss && metrics.dailyLossPct >= config.maxDailyLossPct) {
    return { ok: false, reason: 'RISK_DAILY_LOSS_LIMIT' };
  }
  if (metrics.weeklyLossPct >= config.maxWeeklyLossPct) {
    return { ok: false, reason: 'RISK_WEEKLY_LOSS_LIMIT' };
  }
  if (config.autoStopDrawdown && metrics.drawdownPct >= config.maxDrawdownPct) {
    return { ok: false, reason: 'RISK_DRAWDOWN_LIMIT' };
  }
  const posRows = Array.isArray(positions) ? positions : [];
  const distinctSymbols = new Set(posRows.map((p) => String(p.symbol || '').toUpperCase()).filter(Boolean));
  // Binance one-way mode merges adds into one row per symbol — gate on distinct symbols, not row count.
  if (distinctSymbols.size >= config.maxOpenPositions) {
    return { ok: false, reason: 'RISK_MAX_OPEN_POSITIONS' };
  }
  if (metrics.assetExposurePct > config.maxExposurePerAssetPct) {
    return { ok: false, reason: 'RISK_ASSET_EXPOSURE' };
  }
  if (metrics.exposurePct > config.maxPortfolioExposurePct) {
    return { ok: false, reason: 'RISK_PORTFOLIO_EXPOSURE' };
  }
  const lev = metrics.activeLeverage ?? config.maxAllowedLeverage;
  if (lev > config.maxAllowedLeverage) {
    return { ok: false, reason: 'RISK_LEVERAGE_CAP' };
  }
  if (metrics.availableTradingCapital <= 0 && metrics.freeMargin <= 0) {
    return { ok: false, reason: 'RISK_NO_AVAILABLE_CAPITAL' };
  }
  return { ok: true };
}

export function sizingEquityFromRiskDesk(metrics) {
  return Math.max(0, metrics.availableTradingCapital || metrics.tradableBase || 0);
}
