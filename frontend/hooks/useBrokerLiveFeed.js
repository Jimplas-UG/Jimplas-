import { getBrokerMode, defaultSymbolForBroker } from '../lib/brokerMode';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
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
  loadBars = true,
}) {
  const { setBaseUrl } = useBinanceBridge();
  const sym = symbol ?? defaultSymbolForBroker();
  const feed = useBinanceLiveFeed({
    baseUrl,
    connected,
    enabled,
    symbol: sym,
    pollTicks,
    loadBars,
    publicQuotes: true,
    onBridgeUrlResolved: setBaseUrl,
  });
  return { ...feed, brokerMode: getBrokerMode(), isBinance: true };
}
