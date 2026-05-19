import type {
  BilshenzEngineConfig,
  EquityRiskContext,
  GateSnapshot,
  RiskSnapshot,
  SessionSnapshot,
  SignalSnapshot,
  TradeRecommendation,
} from './types';
import { computeConfidencePct } from './confidenceEngine';
import { applyBalancedClampGeometry, clampTp1ForJournal, rewardRiskRatio } from './tradeGeometry';
import { closedM15BarsInWindow, M30_MS } from './m15Bars';
import { halfLossExitPrice, isAdverseM15Close, underwaterRiskFraction } from './m15AdverseExit';
import type { Bar, TradeJournalRow } from './types';

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
  barLow?: number;
  barHigh?: number;
  setupLevels?: { setup: 'P1' | 'P2' | 'P3'; entry: number; sl: number; tp1: number } | null;
  openJournalRow?: TradeJournalRow | null;
  m30?: Bar[];
  m15?: Bar[];
  equityRisk?: EquityRiskContext | null;
}): TradeRecommendation {
  const {
    cfg,
    session,
    gates,
    risk,
    signals,
    close,
    nearestRes,
    nearestSup,
    slBuffer,
    bullClean,
    bearClean,
    barLow,
    barHigh,
    setupLevels,
    openJournalRow,
    m30,
    m15,
    equityRisk,
  } = args;

  const pineMode = cfg.usePineV5 !== false;
  const sessionTradeOk = pineMode ? session.inSession : session.inSession || cfg.showHistory;
  const blocks: string[] = [];
  if (!sessionTradeOk) blocks.push('Outside session (dead zone)');
  if (cfg.newsActive) blocks.push('News filter active');
  if (cfg.nfpBlackout) blocks.push('NFP/CPI blackout');
  if (risk.brokerSpreadBlocked) blocks.push('Broker spread guard');
  if (!pineMode && risk.barRangeBlocked) blocks.push('M30 bar range guard');
  if (!gates.structureOk) blocks.push('No M30 structure (R/S)');
  if (gates.maxTradesReached) blocks.push(`Max daily trades (${cfg.maxDailyTrades})`);
  if (risk.dxyBlocksBuy) blocks.push('DXY rising — buy blocked');
  if (risk.athZoneBlocked) blocks.push('ATH wick zone — buy blocked');
  if (risk.geoHigh) blocks.push('Geopolitical HIGH');

  if (equityRisk && cfg.maxDailyLossPct > 0 && equityRisk.dayStartEquity > 0) {
    const dayLossPct =
      ((equityRisk.dayStartEquity - equityRisk.currentEquity) / equityRisk.dayStartEquity) * 100;
    if (dayLossPct >= cfg.maxDailyLossPct) {
      blocks.push(`Daily loss limit (${cfg.maxDailyLossPct}% from day start)`);
    }
  }
  if (equityRisk && cfg.maxDrawdownPct > 0 && equityRisk.peakEquity > 0) {
    const ddPct =
      ((equityRisk.peakEquity - equityRisk.currentEquity) / equityRisk.peakEquity) * 100;
    if (ddPct >= cfg.maxDrawdownPct) {
      blocks.push(`Drawdown limit (${cfg.maxDrawdownPct}% from peak)`);
    }
  }

  const conf = computeConfidencePct({ session, gates, risk, cfg, bullClean, bearClean });

  const pickBuy = signals.p1Buy || signals.p2Buy || signals.p3Buy;
  const pickSell = signals.p1Sell || signals.p2Sell || signals.p3Sell;
  const side = pickBuy && !pickSell ? 'BUY' : pickSell && !pickBuy ? 'SELL' : pickBuy && pickSell ? (signals.p1Buy ? 'BUY' : 'SELL') : null;
  const setup: 'P1' | 'P2' | 'P3' | null =
    setupLevels?.setup ??
    (signals.p1Buy || signals.p1Sell ? 'P1' : signals.p2Buy || signals.p2Sell ? 'P2' : signals.p3Buy || signals.p3Sell ? 'P3' : null);

  let allowed = !!(side && sessionTradeOk && blocks.length === 0 && gates.structureOk && !gates.maxTradesReached);
  if (side === 'BUY' && (risk.dxyBlocksBuy || risk.athZoneBlocked)) allowed = false;
  if (side === 'SELL' && risk.geoHigh) allowed = false;

  let entry: number | null = close;
  let sl: number | null = null;
  let tp1: number | null = null;
  if (setupLevels != null && side) {
    sl = setupLevels.sl;
    tp1 = setupLevels.tp1;
  } else {
    const pineSl = cfg.usePineV5 !== false;
    if (side === 'BUY') {
      sl = pineSl && barLow != null ? barLow - slBuffer : close - slBuffer;
      tp1 = nearestRes;
    } else if (side === 'SELL') {
      sl = pineSl && barHigh != null ? barHigh + slBuffer : close + slBuffer;
      tp1 = nearestSup;
    }
  }

  if (cfg.usePineV5 !== false && side) {
    allowed = side === 'BUY' ? signals.anyBuy : signals.anySell;
  }

  if (side && entry != null && sl != null) {
    if (cfg.useLegacyTpClampOnly) {
      const st = setup ?? 'P2';
      const bal = applyBalancedClampGeometry(side, entry, sl, tp1, st, cfg);
      sl = bal.sl;
      tp1 = bal.tp1;
    } else if (side === 'BUY') {
      tp1 = clampTp1ForJournal('BUY', entry, sl, tp1, cfg);
    } else {
      tp1 = clampTp1ForJournal('SELL', entry, sl, tp1, cfg);
    }
  }

  let rr: number | null = null;
  if (entry != null && sl != null && tp1 != null && side) {
    rr = rewardRiskRatio(entry, sl, tp1, side);
  }

  if (cfg.usePineV5 === false) {
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
  }

  const reasonParts: string[] = [];
  if (setup) reasonParts.push(`Setup ${setup} — Jimplas Fluidity`);
  if (cfg.useLegacyTpClampOnly) {
    reasonParts.push(`TP clamp ${cfg.tp1MinRewardPips}–${cfg.tp1MaxRewardPips} pips`);
  } else if (setup === 'P1') {
    reasonParts.push('S/R breakout + retest, structure TP');
  } else if (setup === 'P2') {
    reasonParts.push('Wick fill zone TP');
  } else if (setup === 'P3') {
    reasonParts.push('Session impulse, fixed R:R');
  }
  if (risk.chopZone) reasonParts.push('Chop zone: wick-only path active');

  let m15EarlyExit: { exitPrice: number; message: string } | null = null;
  if (
    cfg.enableM15AdverseExit &&
    openJournalRow?.out === 'OPEN' &&
    openJournalRow.m15ExitWatch &&
    m30?.length &&
    m15?.length
  ) {
    const row = openJournalRow;
    const idx = m30.length - 1;
    const afterMs = row.m15CheckedThroughMs ?? m30[row.barIndex]!.t;
    const upToCloseMs = m30[idx]!.t + M30_MS;
    const window = closedM15BarsInWindow(m15, afterMs, upToCloseMs);
    const last = window[window.length - 1];
    if (
      last &&
      isAdverseM15Close(row, last) &&
      underwaterRiskFraction(row, last.c) >= cfg.m15MinRiskPctBeforeExit
    ) {
      m15EarlyExit = {
        exitPrice: halfLossExitPrice(row),
        message: 'M15 closed against position — exit at half loss (SL under prior M30)',
      };
    }
  }

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
    m15EarlyExit,
  };
}
