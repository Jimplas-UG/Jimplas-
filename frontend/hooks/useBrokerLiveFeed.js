import { getBrokerMode, defaultSymbolForBroker } from '../lib/brokerMode';
import { useBinanceLiveFeed } from './useBinanceLiveFeed';

/**
 * Binance USD-M Futures live feed — quotes, M30 bars, account, fills.
 */
export function useBrokerLiveFeed({
  baseUrl,
  connected,
  enabled = true,
  symbol,
  pollTicks = true,
}) {
  const sym = symbol ?? defaultSymbolForBroker();
  const feed = useBinanceLiveFeed({
    baseUrl,
    connected,
    enabled,
    symbol: sym,
    pollTicks,
    publicQuotes: true,
  });
  return { ...feed, brokerMode: getBrokerMode(), isBinance: true };
}
