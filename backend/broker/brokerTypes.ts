/** Payload your webhook / bridge can map to MT5, OANDA, cTrader, etc. */
export type BrokerOrderIntent = {
  source: 'bilshenz_v3';
  /** ISO time the intent was built (bar time in backtest mode). */
  intentAtIso: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  setup: 'P1' | 'P2' | 'P3' | 'NONE';
  entry: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  confidencePct: number | null;
  barTimeIso: string | null;
  runMode: 'live' | 'backtest';
  /** `manual` = user EXEC; `auto` = engine qualified signal (journal row added that bar). */
  trigger: 'manual' | 'auto';
};

export type BrokerWebhookResult = {
  ok: boolean;
  status: number;
  bodySnippet: string;
};
