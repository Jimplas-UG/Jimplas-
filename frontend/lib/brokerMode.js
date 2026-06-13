/** Broker execution mode — mt5 (default) | binance | paper */
export function getBrokerMode() {
  const m = (process.env.EXPO_PUBLIC_BROKER_MODE || 'mt5').trim().toLowerCase();
  return m === 'binance' || m === 'paper' ? m : 'mt5';
}

export function isBinanceBroker() {
  const m = getBrokerMode();
  return m === 'binance' || m === 'paper';
}

export function defaultSymbolForBroker() {
  return isBinanceBroker() ? 'XAUUSDT' : 'XAUUSD';
}
