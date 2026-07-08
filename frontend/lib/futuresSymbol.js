/**
 * Binance USD-M Futures symbol helpers — no single-asset assumptions.
 */

/** Default chart symbol when the user has not selected one. */
export const DEFAULT_CHART_SYMBOL = 'BTCUSDT';

/** @deprecated Use DEFAULT_CHART_SYMBOL or an explicit symbol from scanner/positions. */
export const TRADING_SYMBOL = DEFAULT_CHART_SYMBOL;

export function normalizeFuturesSymbol(symbol) {
  return String(symbol || '').trim().toUpperCase();
}

export function isValidFuturesSymbol(symbol) {
  const s = normalizeFuturesSymbol(symbol);
  return /^[A-Z0-9]{2,20}USDT$/.test(s);
}

/** e.g. BTCUSDT → BTC/USDT */
export function formatPairLabel(symbol) {
  const s = normalizeFuturesSymbol(symbol);
  if (!s) return '—';
  if (s.endsWith('USDT') && s.length > 4) return `${s.slice(0, -4)}/USDT`;
  return s;
}

/** Display label for headers and compact price strips. */
export const TRADING_PAIR_LABEL = formatPairLabel(DEFAULT_CHART_SYMBOL);

export function baseAsset(symbol) {
  const s = normalizeFuturesSymbol(symbol);
  return s.endsWith('USDT') ? s.slice(0, -4) : s;
}
