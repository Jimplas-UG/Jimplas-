import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useBrokerLiveFeed } from './useBrokerLiveFeed';
import { useRiskDesk } from './useRiskDesk';
import { postBinanceMarginMode } from '../broker/binanceFuturesApi';
import { syncScannerBridgeState } from '../lib/scannerRiskSync';
import { defaultSymbolForBroker } from '../lib/brokerMode';
import { TRADING_SYMBOL } from '../lib/tradingSymbol';
import { resolveAccountEquity } from '../utils/riskSizing';
import { SIM_DESK_EQUITY } from '../security/deskConstants';

const SCANNER_RISK_RESYNC_MS = 90000;

/**
 * Shared Binance session — live feed, risk desk metrics, margin mode handler.
 */
export function useDeskSession() {
  const { baseUrl, connected, sessionEpoch } = useBinanceBridge();
  const [lastBrokerMsg, setLastBrokerMsg] = useState('');
  const lastSyncKeyRef = useRef('');

  const brokerFeed = useBrokerLiveFeed({
    baseUrl,
    connected,
    enabled: !!baseUrl?.trim(),
    symbol: defaultSymbolForBroker(),
    pollTicks: true,
  });

  const useBrokerSession = connected;

  const accountEquity = useMemo(() => {
    if (!useBrokerSession) return SIM_DESK_EQUITY;
    if (brokerFeed.account) return resolveAccountEquity(brokerFeed.account, SIM_DESK_EQUITY);
    return SIM_DESK_EQUITY;
  }, [useBrokerSession, brokerFeed.account]);

  const riskDesk = useRiskDesk({
    brokerAccount: useBrokerSession ? brokerFeed.account : null,
    brokerPositions: useBrokerSession ? brokerFeed.positions : [],
    brokerDeals: useBrokerSession ? brokerFeed.brokerDeals : [],
    markPrice: brokerFeed.price,
    simEquity: SIM_DESK_EQUITY,
  });

  const positions = useBrokerSession ? brokerFeed.positions : [];

  const syncScannerRisk = useCallback(async () => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return;
    const syncKey = [
      baseUrl,
      riskDesk.config.partitionUsd,
      riskDesk.config.shortPartitionPct,
      riskDesk.config.long1PartitionPct,
      riskDesk.config.long2PartitionPct,
    ].join('|');
    if (syncKey === lastSyncKeyRef.current) return;
    lastSyncKeyRef.current = syncKey;

    const r = await syncScannerBridgeState(baseUrl, { config: riskDesk.config }, { retries: 3, delayMs: 700 });
    if (!r.ok) {
      lastSyncKeyRef.current = '';
      console.warn('[desk] scanner risk sync failed', r.risk?.error || r);
    }
  }, [baseUrl, connected, riskDesk.config, riskDesk.hydrated]);

  const handleMarginModeChange = useCallback(
    async (mode) => {
      const next = mode === 'CROSS' ? 'CROSS' : 'ISOLATED';
      riskDesk.updateConfig({ marginMode: next });
      if (!useBrokerSession || !baseUrl) return;
      const r = await postBinanceMarginMode(baseUrl, {
        symbol: brokerFeed.resolvedSymbol || TRADING_SYMBOL,
        marginType: next,
      });
      if (r.ok) {
        brokerFeed.refreshBrokerSnapshot?.();
        setLastBrokerMsg(`Margin: ${next}`);
      } else {
        setLastBrokerMsg(`Margin: ${r.bodySnippet || 'failed'}`);
      }
    },
    [useBrokerSession, baseUrl, brokerFeed, riskDesk.updateConfig],
  );

  useEffect(() => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return undefined;
    lastSyncKeyRef.current = '';
    void syncScannerRisk();
    return undefined;
  }, [baseUrl, connected, sessionEpoch, riskDesk.hydrated, syncScannerRisk]);

  useEffect(() => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return undefined;
    const id = setInterval(() => {
      lastSyncKeyRef.current = '';
      void syncScannerRisk();
    }, SCANNER_RISK_RESYNC_MS);
    return () => clearInterval(id);
  }, [
    baseUrl,
    connected,
    riskDesk.hydrated,
    syncScannerRisk,
    riskDesk.config.partitionUsd,
    riskDesk.config.shortPartitionPct,
    riskDesk.config.long1PartitionPct,
    riskDesk.config.long2PartitionPct,
  ]);

  return {
    baseUrl,
    connected,
    brokerFeed,
    riskDesk,
    useBrokerSession,
    accountEquity,
    lastBrokerMsg,
    setLastBrokerMsg,
    handleMarginModeChange,
  };
}

