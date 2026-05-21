/** Forward demo / production execution validation event log (append-only JSONL). */

export type ForwardDemoEventType =
  | 'SIGNAL'
  | 'ORDER_INTENT'
  | 'ORDER_FILL'
  | 'ORDER_REJECTED'
  | 'MISSED_TRADE'
  | 'EQUITY_SNAPSHOT'
  | 'EXECUTION_MISMATCH';

export type ForwardDemoEvent = {
  id: string;
  ts: string;
  tsMs: number;
  type: ForwardDemoEventType;
  symbol: string;
  side?: 'BUY' | 'SELL';
  setup?: 'P1' | 'P2' | 'P3' | null;
  /** Engine signal bar time (ISO). */
  signalTs?: string;
  signalTsMs?: number;
  intendedEntry?: number;
  intendedSl?: number;
  intendedTp?: number;
  actualFill?: number;
  slippagePips?: number;
  spreadAtExecutionPips?: number;
  latencyMs?: number;
  rejected?: boolean;
  rejectReason?: string;
  missed?: boolean;
  missReason?: string;
  equityUsd?: number;
  broker?: string;
  retcode?: number;
  ticket?: number;
  meta?: Record<string, unknown>;
};

export type SimBaseline30d = {
  windowDays: 30;
  generatedAt: string;
  startEquity: number;
  endEquity: number;
  netPct: number;
  trades: number;
  winRatePct: number;
  profitFactor: number;
  maxDrawdownUsd: number;
  spreadPips: number;
  slippagePipsPerSide: number;
};

export type LivePeriodStats = {
  trades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  profitFactor: number;
  grossProfit: number;
  grossLoss: number;
  netPnlUsd: number;
  startEquity: number;
  endEquity: number;
  maxDrawdownUsd: number;
  avgSlippagePips: number;
  maxSlippagePips: number;
  avgSpreadPips: number;
  avgLatencyMs: number;
  rejectedOrders: number;
  missedTrades: number;
  executionMismatches: number;
};

export type DriftMetrics = {
  winRateDriftPct: number;
  pfDriftPct: number;
  returnDriftPct: number;
  tradeCountDriftPct: number;
  slippageVsSimPips: number;
};

export type ValidationAlert = {
  code: string;
  severity: 'CRITICAL' | 'WARN' | 'INFO';
  message: string;
  value?: number;
  threshold?: number;
};

export type ExecutionAuditScores = {
  simVsLiveVariancePct: number;
  brokerExecutionQuality: number;
  realMoneyReadiness: number;
  recommendedAccountTier: 'micro' | '$1k' | '$5k' | '$25k' | 'scale_larger';
};
