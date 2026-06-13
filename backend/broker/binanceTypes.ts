export type BinanceOrderResult = {
  ok: boolean;
  status: number;
  bodySnippet: string;
  connected?: boolean;
  intendedPrice?: number;
  fillPrice?: number;
  spreadPips?: number;
  slippagePips?: number;
  latencyMs?: number;
  orderId?: number;
  clientOrderId?: string;
  broker?: string;
};

export type BinanceBar = { t: number; o: number; h: number; l: number; c: number };

export type BinanceTick = {
  symbol?: string;
  bid: number;
  ask: number;
  time?: number;
};

export type BinanceSymbolSpec = {
  symbol: string;
  tickSize: number;
  stepSize: number;
  minQty: number;
  maxQty: number;
  pipSize: number;
  volume_min?: number;
  volume_step?: number;
  volume_max?: number;
};
