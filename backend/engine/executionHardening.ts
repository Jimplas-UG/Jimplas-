import type { BilshenzEngineConfig, RiskSnapshot, SessionSnapshot } from './types';

export type MarketRegime = 'TREND' | 'CHOP' | 'HIGH_VOL' | 'LOW_LIQ' | 'NORMAL';

export type ExecutionHardeningView = {
  regime: MarketRegime;
  spreadProxyPips: number;
  adaptiveSpreadLimitPips: number;
  hostileExecution: boolean;
  tradeQualityMin: number;
};

export function classifyMarketRegime(args: {
  atrPips: number | null;
  inSession: boolean;
  chopZone: boolean;
  bullClean: boolean;
  bearClean: boolean;
  cfg: BilshenzEngineConfig;
}): MarketRegime {
  const { atrPips, inSession, chopZone, bullClean, bearClean, cfg } = args;
  if (!inSession && !cfg.showHistory) return 'LOW_LIQ';
  if (atrPips != null && atrPips >= cfg.hostileAtrPips) return 'HIGH_VOL';
  if (chopZone && atrPips != null && atrPips < cfg.volChopMaxAtrPips) return 'CHOP';
  if ((bullClean || bearClean) && atrPips != null && atrPips >= cfg.volTrendMinAtrPips && atrPips < cfg.hostileAtrPips) {
    return 'TREND';
  }
  return 'NORMAL';
}

/** Broker spread for adaptive filter (do not mix bar range — XAU M30 range dwarfs pip spread). */
export function spreadProxyPips(cfg: BilshenzEngineConfig, _barRangePips?: number): number {
  return cfg.currentSpreadPips;
}

/** Wide-bar stress add-on for hostile kill-switch only (pips above typical M30 range). */
export function barRangeStressPips(barRangePips: number): number {
  if (barRangePips >= 120) return 4;
  if (barRangePips >= 85) return 2;
  return 0;
}

export function evaluateExecutionHardening(args: {
  cfg: BilshenzEngineConfig;
  risk: RiskSnapshot;
  session: SessionSnapshot;
  barRangePips: number;
  bullClean: boolean;
  bearClean: boolean;
}): ExecutionHardeningView {
  const { cfg, risk, session, barRangePips, bullClean, bearClean } = args;
  const spreadPx = spreadProxyPips(cfg);
  const baseline = cfg.spreadBaselinePips > 0 ? cfg.spreadBaselinePips : cfg.currentSpreadPips;
  const adaptiveSpreadLimitPips = Math.min(
    cfg.maxSpreadPips,
    Math.max(baseline * cfg.spreadAdaptiveMaxMult, cfg.maxSpreadPips * 0.85)
  );
  const hostileExecution = spreadPx > baseline * cfg.hostileSpreadMult;

  const regime = classifyMarketRegime({
    atrPips: risk.atrPips,
    inSession: session.inSession,
    chopZone: risk.chopZone,
    bullClean,
    bearClean,
    cfg,
  });

  let tradeQualityMin = cfg.minTradeQualityP1P3;
  if (hostileExecution) tradeQualityMin += 12;
  else if (regime === 'HIGH_VOL') tradeQualityMin += 6;
  else if (regime === 'CHOP') tradeQualityMin += 4;

  return {
    regime,
    spreadProxyPips: spreadPx,
    adaptiveSpreadLimitPips,
    hostileExecution,
    tradeQualityMin,
  };
}

export function adaptiveSpreadBlocked(cfg: BilshenzEngineConfig, spreadProxy: number, limit: number): boolean {
  return spreadProxy > cfg.maxSpreadPips || spreadProxy > limit;
}

export function tradeQualityScore(args: {
  setup: 'P1' | 'P2' | 'P3' | null;
  rr: number | null;
  confidencePct: number;
  spreadProxy: number;
  adaptiveLimit: number;
  regime: MarketRegime;
  bullClean: boolean;
  bearClean: boolean;
}): number {
  const { setup, rr, confidencePct, spreadProxy, adaptiveLimit, regime, bullClean, bearClean } = args;
  let score = confidencePct * 0.45;
  if (setup === 'P1') score += 14;
  if (setup === 'P2') score += 6;
  if (setup === 'P3') score += 12;
  if (rr != null && rr >= 1) score += Math.min(22, rr * 12);
  const headroom = Math.max(0, adaptiveLimit - spreadProxy);
  score += Math.min(12, headroom * 4);
  if (regime === 'TREND' && (bullClean || bearClean)) score += 8;
  if (regime === 'CHOP') score -= 10;
  if (regime === 'HIGH_VOL') score -= 6;
  if (regime === 'LOW_LIQ') score -= 15;
  return Math.round(Math.max(0, Math.min(100, score)) * 10) / 10;
}

export function volatilityScaledMaxSlPips(cfg: BilshenzEngineConfig, atrPips: number | null): number {
  const base = cfg.journalSizingSlPips > 0 ? cfg.journalSizingSlPips : 20;
  if (!cfg.enableExecutionHardening || atrPips == null) return base;
  if (atrPips >= cfg.hostileAtrPips) return base * cfg.volSlScaleHigh;
  if (atrPips >= cfg.volTrendMinAtrPips) return base * 1.08;
  return base;
}
