import { getBrokerMode, isBinanceBroker } from '../lib/brokerMode';
import { useMt5LiveFeed } from './useMt5LiveFeed';
import { useBinanceLiveFeed } from './useBinanceLiveFeed';

/**
 * Unified broker feed — MT5 or Binance based on EXPO_PUBLIC_BROKER_MODE.
 */
export function useBrokerLiveFeed({
  mt5BaseUrl,
  mt5Connected,
  binanceBaseUrl,
  binanceConnected,
  enabled = true,
  symbol,
  pollTicks = true,
}) {
  const mode = getBrokerMode();
  const binance = isBinanceBroker();
  const sym = symbol ?? (binance ? 'XAUUSDT' : 'XAUUSD');

  const mt5 = useMt5LiveFeed({
    baseUrl: mt5BaseUrl,
    connected: mt5Connected,
    enabled: enabled && !binance,
    symbol: sym,
    pollTicks,
  });

  const bz = useBinanceLiveFeed({
    baseUrl: binanceBaseUrl,
    connected: binanceConnected,
    enabled: enabled && binance,
    symbol: sym,
    pollTicks,
  });

  const feed = binance ? bz : mt5;
  return { ...feed, brokerMode: mode, isBinance: binance };
}
