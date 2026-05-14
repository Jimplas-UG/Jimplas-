import type {
  BilshenzEngineConfig,
  GateSnapshot,
  RiskSnapshot,
  SessionSnapshot,
  SignalSnapshot,
  TradeRecommendation,
} from './types';
import { computeConfidencePct } from './confidenceEngine';
import { clampTp1ForJournal, rewardRiskRatio } from './tradeGeometry';

export function buildTradeRecommendation(args: {
  cfg: BilshenzEngineConfig;
  session: SessionSnapshot;
  gates: GateSnapshot;
  risk: RiskSnapshot;
  signals: SignalSnapshot;
  close: number;
  nearestRes: number | null;
  nearestSup: number | null;
  slBuffer: number;
  bullClean: boolean;
  bearClean: boolean;
}): TradeRecommendation {
  const { cfg, session, gates, risk, signals, close, nearestRes, nearestSup, slBuffer, bullClean, bearClean } = args;

  const sessionTradeOk = session.inSession || cfg.showHistory;
  const blocks: string[] = [];
  if (!sessionTradeOk) blocks.push('Outside session (dead zone)');
  if (cfg.newsActive) blocks.push('News filter active');
  if (cfg.nfpBlackout) blocks.push('NFP/CPI blackout');
  if (risk.brokerSpreadBlocked) blocks.push('Broker spread guard');
  if (risk.barRangeBlocked) blocks.push('M30 bar range guard (Pine)');
  if (!gates.structureOk) blocks.push('No M30 structure (R/S)');
  if (gates.maxTradesReached) blocks.push(`Max daily trades (${cfg.maxDailyTrades})`);
  if (risk.dxyBlocksBuy) blocks.push('DXY rising — buy blocked');
  if (risk.athZoneBlocked) blocks.push('ATH wick zone — buy blocked');
  if (risk.geoHigh) blocks.push('Geopolitical HIGH');

  const conf = computeConfidencePct({ session, gates, risk, cfg, bullClean, bearClean });

  const pickBuy = signals.p1Buy || signals.p2Buy || signals.p3Buy;
  const pickSell = signals.p1Sell || signals.p2Sell || signals.p3Sell;
  const side = pickBuy && !pickSell ? 'BUY' : pickSell && !pickBuy ? 'SELL' : pickBuy && pickSell ? (signals.p1Buy ? 'BUY' : 'SELL') : null;
  const setup: 'P1' | 'P2' | 'P3' | null = signals.p1Buy || signals.p1Sell ? 'P1' : signals.p2Buy || signals.p2Sell ? 'P2' : signals.p3Buy || signals.p3Sell ? 'P3' : null;

  let allowed = !!(side && sessionTradeOk && blocks.length === 0 && gates.structureOk && !gates.maxTradesReached);
  if (side === 'BUY' && (risk.dxyBlocksBuy || risk.athZoneBlocked)) allowed = false;
  if (side === 'SELL' && risk.geoHigh) allowed = false;

  let entry: number | null = close;
  let sl: number | null = null;
  let tp1: number | null = null;
  if (side === 'BUY') {
    sl = close - slBuffer;
    tp1 = nearestRes;
  } else if (side === 'SELL') {
    sl = close + slBuffer;
    tp1 = nearestSup;
  }

  if (side === 'BUY' && entry != null && sl != null) {
    tp1 = clampTp1ForJournal('BUY', entry, sl, tp1, cfg);
  } else if (side === 'SELL' && entry != null && sl != null) {
    tp1 = clampTp1ForJournal('SELL', entry, sl, tp1, cfg);
  }

  let rr: number | null = null;
  if (entry != null && sl != null && tp1 != null && side) {
    rr = rewardRiskRatio(entry, sl, tp1, side);
  }

  if (allowed && conf < cfg.minConfidencePctToTrade) {
    allowed = false;
    blocks.push(`Confidence ${conf.toFixed(0)}% < ${cfg.minConfidencePctToTrade}% (quality gate)`);
  }
  if (allowed && rr != null && rr < cfg.minRewardRiskToTrade) {
    allowed = false;
    blocks.push(`R:R ${rr.toFixed(2)} < ${cfg.minRewardRiskToTrade} (min reward:risk)`);
  }
  if (allowed && setup === 'P3' && rr != null && rr < cfg.p3MinRewardRisk) {
    allowed = false;
    blocks.push(`P3 R:R ${rr.toFixed(2)} < ${cfg.p3MinRewardRisk} (stricter flip retest)`);
  }

  const reasonParts: string[] = [];
  if (setup) reasonParts.push(`Setup ${setup} per Bilshenz v3.2`);
  if (signals.p1Buy || signals.p1Sell) reasonParts.push('Liquidity sweep wick / rejection stack');
  if (signals.p2Buy || signals.p2Sell) reasonParts.push('M30 breakout with body/wick rules');
  if (signals.p3Buy || signals.p3Sell) reasonParts.push('S/R flip retest rejection');
  if (risk.chopZone) reasonParts.push('Chop zone: wick-only path active');

  return {
    allowed,
    side,
    setup,
    entry,
    sl,
    tp1,
    rr,
    confidencePct: conf,
    reason: reasonParts.join(' · ') || 'No active Pine-qualified setup on this bar',
    blocks,
  };
}
