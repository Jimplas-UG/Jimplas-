/** OHLCV bar (time ascending). */
export type Bar = { t: number; o: number; h: number; l: number; c: number; v?: number };

export type GeoRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

/** Mirrors Pine script inputs + runtime flags. */
export type BilshenzEngineConfig = {
  pipSize: number;
  newsActive: boolean;
  nfpBlackout: boolean;
  currentSpreadPips: number;
  useDxyFilter: boolean;
  useYieldFilter: boolean;
  geoRisk: GeoRiskLevel;
  showHistory: boolean;
  /** When true, relax master_block for signal math (Pine: master_block := false). */
  showHistoryMode: boolean;
  /** Use original TradingView Pine v5 entry logic (P1/P2/P3, pivot 3/3, left-side clean). */
  usePineV5: boolean;
  /** Jimplas Fluidity — toggle each setup module. */
  enableP1: boolean;
  enableP2: boolean;
  enableP3: boolean;
  /** P1: min candle range vs ATR for “high volume” breakout. */
  p1VolumeAtrMult: number;
  p1ConsolidationLookback: number;
  p1ConsolidationMinBars: number;
  p1ConsolidationMaxBars: number;
  p1CleanTrafficMaxChop: number;
  /** P2: wick-fill zone scan. */
  p2WickLookback: number;
  p2WickMinRatio: number;
  p2CleanTrafficLookback: number;
  /** P2: max body ratio on rejection candle (smaller body = stronger wick). */
  p2MaxBodyRatio: number;
  /** P2: min rejection wick size (pips). */
  p2MinWickPips: number;
  /** P2: min void height to fill (pips). */
  p2MinVoidPips: number;
  /** P2: max void height — skip oversized wicks (pips). */
  p2MaxVoidPips: number;
  /** P2: max consolidating bars inside void (clean traffic). */
  p2MaxChopInVoid: number;
  /** P2: require H4+daily bias with trade direction. */
  p2RequireBias: boolean;
  /** P2: require Jimplas flip on entry bar. */
  p2RequireFlip: boolean;
  /** P2: require M30 close beyond prior bar H/L (not wick-only break). */
  p2RequireCloseBreak: boolean;
  /** P2: block when ATR chop zone is active. */
  p2BlockInChopZone: boolean;
  /** When false, P2 uses loose wick-fill entries (~500+ trades/yr). When true, strict filters (~30–100/yr). */
  p2UseStrictFilters: boolean;
  /** With legacy TP clamp: floor TP at this × SL distance (capped by tp1MaxRewardPips). */
  tpClampMinRiskReward: number;
  /** TP target as fraction of SL distance (e.g. 0.7 = 70% of SL pips), keeps wide SL + reachable TP. */
  tpClampSlFraction: number;
  /** Skip new entries when raw SL exceeds this (0 = allow all). */
  maxSlPipsForEntry: number;
  /** Scale down $ risk when SL pips exceed TP cap (keeps ~volume, fixes wide-SL negative expectancy). */
  riskScaleWideStops: boolean;
  /** Fixed SL pips for $ risk sizing when structural SL is wider (0 = use actual SL pips). */
  journalSizingSlPips: number;
  /** M15 half-exit only after price has moved this fraction of entry→SL risk against the trade. */
  m15MinRiskPctBeforeExit: number;
  /** P3: fixed R:R (1 or 2) at session open. */
  p3RewardRisk: number;
  p3LondonOnly: boolean;
  p3NewYorkOnly: boolean;
  /** ATR period (Pine: 14). */
  atrLen: number;
  /** M30 S&R pivot left/right (Pine v5: 3, 3). */
  pivotLeft: number;
  pivotRight: number;
  /** Pivot window for M30 HH/HL bias row (Pine: 5, 5). */
  structurePivotLeft: number;
  structurePivotRight: number;
  /** Zone half-width in pips (Pine zone_pip = 3 × pip_size). */
  zoneHalfWidthPips: number;
  /** Max pivot levels kept per side (Pine i_sr_history: 8). */
  srHistoryMax: number;
  /** Left-side lookback bars (Pine i_ls_bars: 40). */
  leftScanBars: number;
  /** Max chop closes allowed in path (Pine i_ls_chop: 3). */
  leftScanMaxChop: number;
  /** Min lower/upper wick ratio for E1 (Pine i_wick_r: 0.60). */
  wickRatioMin: number;
  /** Min body ratio for E2 (Pine i_body_r: 0.40). */
  bodyRatioMin: number;
  /** ATH zone (Pine hard-coded). */
  athZoneLow: number;
  athZoneHigh: number;
  /** Yield threshold % (Pine: 4.4). */
  yieldHighThreshold: number;
  /** Max spread pips (Pine: 3.5). */
  maxSpreadPips: number;
  /** Min range pips (Pine: 25). */
  minRangePips: number;
  /** Daily max trades (Pine default was 3; higher values increase how many signals may journal per NY day). */
  maxDailyTrades: number;
  /**
   * Equity % at stop — ATR sizing stack (values are **percent points**: 1.0 = 1% of account).
   * Capped by {@link riskPctGeoHighCap} when geoRisk is HIGH.
   */
  riskPctAtrNormal: number;
  riskPctAtrElevated: number;
  riskPctAtrCrisis: number;
  riskPctGeoHighCap: number;
  /**
   * Journal / trade-bot stop distance from entry in **pips** (price offset = journalSlPips × pipSize).
   * Pine signal lines use ~2 (bar extreme ± 2×PIP); widen for looser sim SL.
   */
  journalSlPips: number;
  /** After any closed LOSS, block new signals for this many bars (0 = off). */
  lossCooldownBars: number;
  /** After a P3 LOSS on a side, block that side’s P3 for this many bars (0 = off). */
  p3SameSideBarsAfterP3Loss: number;
  /** Max P3 entries per side within {@link p3LookbackBars} (0 = off). */
  p3MaxSameSideInLookback: number;
  /** Rolling window (bars) for {@link p3MaxSameSideInLookback}. */
  p3LookbackBars: number;
  /** Minimum bars after a P3 loss before clear/sweep retest can qualify. */
  p3RetestWaitBars: number;
  /** After P3 BUY loss: max high since loss must reach entry + this many pips (0 = skip this leg). */
  p3RetestClearPips: number;
  /** After P3 BUY loss: min low since loss must reach entry − this many pips (0 = skip). SELL uses mirrored logic. */
  p3RetestSweepPips: number;
  /** E1 wick ratio floor (can be slightly below {@link wickRatioMin} to surface more P1). */
  p1WickRatioMin: number;
  /** E2 body ratio floor (can be slightly below {@link bodyRatioMin}). */
  p2BodyRatioMin: number;
  /** E2: allow open within this many pips of imm (0 = strict Pine). */
  e2NearImmZonePips: number;
  /** Minimum entry→TP1 distance (pips) so TP stays on profit side after zone targets. */
  tp1MinRewardPips: number;
  /** Cap entry→TP1 distance (pips) — legacy clamp; not applied to Jimplas P1/P2 when 0. */
  tp1MaxRewardPips: number;
  /** P1 minimum R:R after structure TP (default 1:1). */
  p1MinRewardRisk: number;
  /** P2 minimum R:R to wick-tip / zone-end target. */
  p2MinRewardRisk: number;
  /** P1 max TP distance in pips (0 = structure level only, no cap). */
  p1MaxTpPips: number;
  /** P2 max TP distance in pips (0 = wick/zone target only). */
  p2MaxTpPips: number;
  /** P1 max SL distance in pips from entry (0 = no cap). */
  p1MaxSlPips: number;
  /** P2 max SL distance in pips from entry (0 = no cap). */
  p2MaxSlPips: number;
  /** P3 SL buffer pips (0 = exactly at entry candle wick). */
  p3SlBufferPips: number;
  /** After entry (SL under/over prior M30), exit at half loss on adverse M15 close. */
  enableM15AdverseExit: boolean;
  /**
   * When true (default), TP is always clamped to {@link tp1MinRewardPips}–{@link tp1MaxRewardPips}
   * (10–28 pips). Skips per-setup structure TP from Jimplas geometry.
   */
  useLegacyTpClampOnly: boolean;
  /** Block `trade.allowed` when dashboard confidence &lt; this (0–100). */
  minConfidencePctToTrade: number;
  /** Minimum reward:risk (after TP clamp) for any setup. */
  minRewardRiskToTrade: number;
  /** Halt new entries when NY-day loss from day-start equity reaches this % (0 = off). */
  maxDailyLossPct: number;
  /** Halt new entries when drawdown from peak equity reaches this % (0 = off). */
  maxDrawdownPct: number;
  /** Live: evaluate signals on last closed M30 bar (n-2), not the forming bar. */
  signalOnClosedBarOnly: boolean;
  /** Stricter minimum R:R for P3 (retest); must stay compatible with {@link tp1MaxRewardPips} / {@link journalSlPips}. */
  p3MinRewardRisk: number;
  /**
   * Breakeven arm in **price** from entry (Pine: i_be_pips 12 × pip = 1.2 when pipSize 0.1).
   * UI may display as pips via beOffset / pipSize.
   */
  beOffset: number;
  /**
   * Sim UI only: USD per 1 XAU pip of journal distance for closed P&L, lot estimate, profile total.
   * Not a live broker rate; one knob keeps those readouts aligned.
   */
  simUsdPerEnginePip: number;
};

export const defaultBilshenzConfig: BilshenzEngineConfig = {
  pipSize: 0.1,
  newsActive: false,
  nfpBlackout: false,
  currentSpreadPips: 1.5,
  useDxyFilter: true,
  useYieldFilter: true,
  geoRisk: 'LOW',
  showHistory: false,
  showHistoryMode: false,
  usePineV5: true,
  enableP1: true,
  enableP2: true,
  enableP3: true,
  p1VolumeAtrMult: 1.15,
  p1ConsolidationLookback: 20,
  p1ConsolidationMinBars: 2,
  p1ConsolidationMaxBars: 18,
  p1CleanTrafficMaxChop: 5,
  p2WickLookback: 40,
  p2WickMinRatio: 0.55,
  p2CleanTrafficLookback: 30,
  p2MaxBodyRatio: 0.53,
  p2MinWickPips: 7,
  p2MinVoidPips: 4,
  p2MaxVoidPips: 42,
  p2MaxChopInVoid: 5,
  p2RequireBias: true,
  p2RequireFlip: false,
  p2RequireCloseBreak: false,
  p2BlockInChopZone: false,
  p2UseStrictFilters: false,
  tpClampMinRiskReward: 1,
  tpClampSlFraction: 0,
  maxSlPipsForEntry: 0,
  riskScaleWideStops: false,
  journalSizingSlPips: 20,
  m15MinRiskPctBeforeExit: 0.45,
  p3RewardRisk: 2,
  p3LondonOnly: true,
  p3NewYorkOnly: true,
  atrLen: 14,
  pivotLeft: 3,
  pivotRight: 3,
  structurePivotLeft: 5,
  structurePivotRight: 5,
  zoneHalfWidthPips: 3,
  srHistoryMax: 8,
  leftScanBars: 40,
  leftScanMaxChop: 3,
  wickRatioMin: 0.6,
  bodyRatioMin: 0.4,
  athZoneLow: 5278.0,
  athZoneHigh: 5602.0,
  yieldHighThreshold: 4.4,
  maxSpreadPips: 3.5,
  minRangePips: 25,
  maxDailyTrades: 3,
  riskPctAtrNormal: 1.0,
  riskPctAtrElevated: 0.7,
  riskPctAtrCrisis: 0.5,
  riskPctGeoHighCap: 0.5,
  journalSlPips: 2,
  lossCooldownBars: 0,
  p3SameSideBarsAfterP3Loss: 0,
  p3MaxSameSideInLookback: 0,
  p3LookbackBars: 96,
  p3RetestWaitBars: 0,
  p3RetestClearPips: 0,
  p3RetestSweepPips: 0,
  p1WickRatioMin: 0.6,
  p2BodyRatioMin: 0.4,
  e2NearImmZonePips: 0,
  tp1MinRewardPips: 14,
  tp1MaxRewardPips: 32,
  p1MinRewardRisk: 1.2,
  p2MinRewardRisk: 1,
  p1MaxTpPips: 45,
  p2MaxTpPips: 24,
  p1MaxSlPips: 35,
  p2MaxSlPips: 16,
  p3SlBufferPips: 0,
  enableM15AdverseExit: true,
  useLegacyTpClampOnly: true,
  minConfidencePctToTrade: 66,
  minRewardRiskToTrade: 0.52,
  /** P3 stricter floor; keep below tp1MaxRewardPips/journalSlPips or wide SL + TP cap blocks all P3. */
  p3MinRewardRisk: 0.62,
  beOffset: 1.2,
  simUsdPerEnginePip: 12.5,
  maxDailyLossPct: 3,
  maxDrawdownPct: 15,
  signalOnClosedBarOnly: true,
};

/** Optional equity context for daily-loss / max-drawdown circuit breakers. */
export type EquityRiskContext = {
  currentEquity: number;
  peakEquity: number;
  dayStartEquity: number;
};

export type SessionName = 'PRE_LONDON' | 'LONDON' | 'NEW_YORK' | 'DEAD';

export type SessionSnapshot = {
  preLondon: boolean;
  london: boolean;
  newYork: boolean;
  inSession: boolean;
  name: SessionName;
  sessionLabel: string;
};

export type BiasSnapshot = {
  /**
   * Pine v3.2 plots EMA50 on the chart TF (M30). Kept as ema50H4 for UI compatibility.
   */
  ema50H4: number | null;
  /** Fast M30 EMA21 — UI “H1 proxy” row (not a separate H1 feed). */
  ema21M30: number | null;
  dHigh0: number | null;
  dHigh1: number | null;
  dLow0: number | null;
  dLow1: number | null;
  bullStructure: boolean;
  bearStructure: boolean;
  isBullish: boolean;
  isBearish: boolean;
};

export type SrStacks = {
  r1: number | null;
  r2: number | null;
  r3: number | null;
  s1: number | null;
  s2: number | null;
  s3: number | null;
  r1Flipped: boolean;
  r2Flipped: boolean;
  r3Flipped: boolean;
  s1Flipped: boolean;
  s2Flipped: boolean;
  s3Flipped: boolean;
};

export type WickMetrics = {
  candleRange: number;
  bodySize: number;
  upperWick: number;
  lowerWick: number;
  bodyRatio: number;
  wickRatio: number;
  /** Pine r_uwk — upper wick / range. */
  upperWickRatio: number;
  /** Pine r_lwk — lower wick / range. */
  lowerWickRatio: number;
  isDoji: boolean;
  isValidBreakout: boolean;
  isValidRejection: boolean;
  jimplasFlipBuy: boolean;
  jimplasFlipSell: boolean;
};

export type RangeCleanSnapshot = {
  bullPips: number;
  bearPips: number;
  bullRangeOk: boolean;
  bearRangeOk: boolean;
  bullClean: boolean;
  bearClean: boolean;
  /** Pine left-side chop count (bull path). */
  bullChop: number;
  /** Pine left-side chop count (bear path). */
  bearChop: number;
};

export type RiskSnapshot = {
  atrVal: number | null;
  atrPips: number | null;
  atrMode: string;
  chopZone: boolean;
  /** Broker spread > maxSpreadPips. */
  brokerSpreadBlocked: boolean;
  /** Pine-style M30 bar range guard: (h−l)/pip > maxSpreadPips×10. */
  barRangeBlocked: boolean;
  /** True if either broker or bar-range guard trips (live master gate). */
  spreadBlocked: boolean;
  dxyRising: boolean;
  dxyBlocksBuy: boolean;
  yieldHigh: boolean;
  athZoneBlocked: boolean;
  geoMedium: boolean;
  geoHigh: boolean;
  h4SwingHigh1: number | null;
  h4SwingHigh2: number | null;
  h4SwingLow1: number | null;
  h4SwingLow2: number | null;
};

export type GateSnapshot = {
  hasStructure: boolean;
  structureOk: boolean;
  masterBlock: boolean;
  sessionGate: boolean;
  liveGateBuy: boolean;
  liveGateSell: boolean;
  hardBlockBuy: boolean;
  hardBlockSell: boolean;
  maxTradesReached: boolean;
};

export type SignalSnapshot = {
  p1Buy: boolean;
  p1Sell: boolean;
  p2Buy: boolean;
  p2Sell: boolean;
  p3Buy: boolean;
  p3Sell: boolean;
  anyBuy: boolean;
  anySell: boolean;
};

export type TradeJournalRow = {
  entry: number;
  sl: number;
  tp1: number | null;
  dir: 'BUY' | 'SELL';
  type: 'P1' | 'P2' | 'P3';
  time: string;
  out: 'OPEN' | 'WIN' | 'LOSS' | 'HALF_LOSS';
  barIndex: number;
  /** Armed when SL is beyond prior M30 bar and M15 adverse-exit is enabled. */
  m15ExitWatch?: boolean;
  /** Last processed M15 close timestamp (ms). */
  m15CheckedThroughMs?: number;
  /** Fill price for HALF_LOSS / early exit. */
  exitPrice?: number;
};

export type WinRateSnapshot = {
  totalWins: number;
  totalLosses: number;
  winRatePct: number;
  p1Wr: number;
  p2Wr: number;
  p3Wr: number;
  journal: TradeJournalRow[];
};

export type TradeRecommendation = {
  allowed: boolean;
  side: 'BUY' | 'SELL' | null;
  setup: 'P1' | 'P2' | 'P3' | null;
  entry: number | null;
  sl: number | null;
  tp1: number | null;
  rr: number | null;
  confidencePct: number;
  reason: string;
  blocks: string[];
  /** Live: close open trade at half loss — adverse M15 just closed. */
  m15EarlyExit?: { exitPrice: number; message: string } | null;
};

export type BilshenzSnapshot = {
  asOf: number;
  session: SessionSnapshot;
  bias: BiasSnapshot;
  sr: SrStacks & {
    nearestRes: number | null;
    nearestSup: number | null;
    poiRes: number | null;
    poiSup: number | null;
    flipSupLevel: number | null;
    flipResLevel: number | null;
    prevNearestRes: number | null;
    prevNearestSup: number | null;
    zonePip: number;
  };
  range: RangeCleanSnapshot;
  wick: WickMetrics;
  risk: RiskSnapshot;
  gates: GateSnapshot;
  signals: SignalSnapshot;
  winRate: WinRateSnapshot;
  trade: TradeRecommendation;
  /** Per-setup SL/TP from Jimplas Fluidity engine (when active). */
  tradeLevels: { setup: 'P1' | 'P2' | 'P3'; entry: number; sl: number; tp1: number } | null;
  structureLevels: {
    pdh: number | null;
    pdl: number | null;
    wh: number | null;
    wl: number | null;
    mh: number | null;
    ml: number | null;
  };
  dxyClose: number | null;
  us10yClose: number | null;
  labelGap: number;
  slBuffer: number;
};

export type MarketBundle = {
  m30: Bar[];
  h4: Bar[];
  d1: Bar[];
  w1: Bar[];
  mn1: Bar[];
  /** DXY closes aligned to same chart timeline as m30 (same length as m30) or at least last value used. */
  dxyCloseSeries: number[];
  /** US10Y % yield closes aligned to m30. */
  us10yCloseSeries: number[];
};
