import type { BilshenzEngineConfig, GateSnapshot, RiskSnapshot, SessionSnapshot } from './types';

/** Mirrors dashboard-style stacked confirmations (Pine-derived gates, not an extra Pine variable). */
export function computeConfidencePct(args: {
  session: SessionSnapshot;
  gates: GateSnapshot;
  risk: RiskSnapshot;
  cfg: BilshenzEngineConfig;
  bullClean: boolean;
  bearClean: boolean;
}): number {
  const { session, gates, risk, cfg, bullClean, bearClean } = args;
  const checks: boolean[] = [
    session.inSession || cfg.showHistory,
    !cfg.newsActive,
    !cfg.nfpBlackout,
    !risk.brokerSpreadBlocked,
    !risk.barRangeBlocked,
    gates.structureOk,
    !gates.maxTradesReached,
    !risk.dxyBlocksBuy,
    !risk.athZoneBlocked,
    !risk.geoHigh,
    bullClean || bearClean,
    !risk.yieldHigh,
    cfg.geoRisk === 'LOW' || cfg.geoRisk === 'MEDIUM',
    gates.liveGateBuy || gates.liveGateSell,
  ];
  const passed = checks.filter(Boolean).length;
  return Math.round((passed / checks.length) * 1000) / 10;
}
