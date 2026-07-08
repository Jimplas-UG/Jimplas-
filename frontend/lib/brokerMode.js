import { DEFAULT_CHART_SYMBOL } from './futuresSymbol';

/** Binance Futures — live keys or paper simulator. */
export function getBrokerMode() {
  const m = (process.env.EXPO_PUBLIC_BROKER_MODE || 'binance').trim().toLowerCase();
  return m === 'paper' ? 'paper' : 'binance';
}

export function isPaperBroker() {
  return getBrokerMode() === 'paper';
}

/** @deprecated alias — app is Binance-only */
export function isBinanceBroker() {
  return true;
}

export function defaultSymbolForBroker() {
  return DEFAULT_CHART_SYMBOL;
}
