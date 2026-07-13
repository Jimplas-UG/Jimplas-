import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useBrokerLiveFeed } from './useBrokerLiveFeed';
import { useRiskDesk } from './useRiskDesk';
import { postBinanceMarginMode } from '../broker/binanceFuturesApi';
import { syncScannerBridgeState, syncScannerExecHalt } from '../lib/scannerRiskSync';
import { defaultSymbolForBroker } from '../lib/brokerMode';
import { DEFAULT_CHART_SYMBOL, sanitizeFuturesSymbol } from '../lib/futuresSymbol';
import { resolveAccountEquity } from '../utils/riskSizing';
import { SIM_DESK_EQUITY } from '../security/deskConstants';

const SCANNER_RISK_RESYNC_MS = 90000;

/**
 * Shared Binance session — live feed, risk desk metrics, margin mode handler.
 */
export function useDeskSession({ enabled = true, loadBars = true, pollTicks = true } = {}) {
  const { baseUrl, connected, sessionEpoch } = useBinanceBridge();
  const [lastBrokerMsg, setLastBrokerMsg] = useState('');
  const lastSyncKeyRef = useRef('');

  const brokerFeed = useBrokerLiveFeed({
    baseUrl,
    connected,
    enabled: enabled && !!baseUrl?.trim(),
    symbol: sanitizeFuturesSymbol(defaultSymbolForBroker(), DEFAULT_CHART_SYMBOL),
    pollTicks: enabled && pollTicks,
    loadBars: enabled && loadBars,
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

  const riskConfigRef = useRef(riskDesk.config);
  riskConfigRef.current = riskDesk.config;

  const partitionUsd = riskDesk.config.partitionUsd;
  const shortPartitionPct = riskDesk.config.shortPartitionPct;
  const long1PartitionPct = riskDesk.config.long1PartitionPct;
  const long2PartitionPct = riskDesk.config.long2PartitionPct;
  const emergencyStop = riskDesk.config.emergencyStop;

  const positions = useBrokerSession ? brokerFeed.positions : [];

  const syncScannerRisk = useCallback(async () => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return;
    const cfg = riskConfigRef.current;
    const syncKey = [
      baseUrl,
      cfg.partitionUsd,
      cfg.shortPartitionPct,
      cfg.long1PartitionPct,
      cfg.long2PartitionPct,
      cfg.emergencyStop ? 'halt' : 'run',
    ].join('|');
    if (syncKey === lastSyncKeyRef.current) return;
    lastSyncKeyRef.current = syncKey;

    const r = await syncScannerBridgeState(baseUrl, { config: cfg }, { retries: 3, delayMs: 700 });
    if (!r.ok) {
      lastSyncKeyRef.current = '';
      console.warn('[desk] scanner risk sync failed', r.risk?.error || r);
    }
  }, [
    baseUrl,
    connected,
    riskDesk.hydrated,
    partitionUsd,
    shortPartitionPct,
    long1PartitionPct,
    long2PartitionPct,
    emergencyStop,
  ]);

  const handleMarginModeChange = useCallback(
    async (mode) => {
      const next = mode === 'CROSS' ? 'CROSS' : 'ISOLATED';
      riskDesk.updateConfig({ marginMode: next });
      if (!useBrokerSession || !baseUrl) return;
      const r = await postBinanceMarginMode(baseUrl, {
        symbol: sanitizeFuturesSymbol(brokerFeed.resolvedSymbol, DEFAULT_CHART_SYMBOL),
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
    void postBinanceMarginMode(baseUrl, {
      symbol: sanitizeFuturesSymbol(defaultSymbolForBroker(), DEFAULT_CHART_SYMBOL),
      marginType: 'ISOLATED',
    }).catch(() => {});
    return undefined;
  }, [baseUrl, connected, sessionEpoch, riskDesk.hydrated, syncScannerRisk]);

  useEffect(() => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return undefined;
    const id = setInterval(() => {
      lastSyncKeyRef.current = '';
      void syncScannerRisk();
    }, SCANNER_RISK_RESYNC_MS);
    return () => clearInterval(id);
  }, [baseUrl, connected, riskDesk.hydrated, syncScannerRisk]);

  const triggerEmergencyStop = useCallback(async () => {
    riskDesk.triggerEmergencyStop();
    if (!baseUrl?.trim() || !connected) return;
    lastSyncKeyRef.current = '';
    const r = await syncScannerExecHalt(baseUrl, false);
    if (!r.ok) {
      console.warn('[desk] emergency stop server sync failed', r.error || r);
    }
  }, [baseUrl, connected, riskDesk.triggerEmergencyStop]);

  const resumeTrading = useCallback(async () => {
    riskDesk.resumeTrading();
    if (!baseUrl?.trim() || !connected) return;
    lastSyncKeyRef.current = '';
    const r = await syncScannerExecHalt(baseUrl, true);
    if (!r.ok) {
      console.warn('[desk] resume trading server sync failed', r.error || r);
    }
  }, [baseUrl, connected, riskDesk.resumeTrading]);

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
    triggerEmergencyStop,
    resumeTrading,
  };
}

