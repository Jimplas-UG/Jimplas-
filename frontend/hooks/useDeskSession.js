import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useBrokerLiveFeed } from './useBrokerLiveFeed';
import { useRiskDesk } from './useRiskDesk';
import { postBinanceMarginMode } from '../broker/binanceFuturesApi';
import {
  enableScannerAutoExecOnConnect,
  scannerExecAllowed,
  syncScannerBridgeState,
} from '../lib/scannerRiskSync';
import { defaultSymbolForBroker } from '../lib/brokerMode';
import { TRADING_SYMBOL } from '../lib/tradingSymbol';
import { resolveAccountEquity } from '../utils/riskSizing';
import { SIM_DESK_EQUITY } from '../security/deskConstants';

const SCANNER_RISK_RESYNC_MS = 90000;
const CONNECT_EXEC_BOOST_MS = 2500;
const CONNECT_EXEC_BOOST_DURATION_MS = 20000;

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

  const effectiveAutoExecute = useMemo(
    () => scannerExecAllowed(riskDesk.config, riskDesk.metrics, positions, connected),
    [riskDesk.config, riskDesk.metrics, positions, connected],
  );

  const syncScannerRisk = useCallback(async () => {
    if (!baseUrl?.trim() || !riskDesk.hydrated) return;
    const execOn = scannerExecAllowed(riskDesk.config, riskDesk.metrics, positions, connected);
    const syncKey = [
      baseUrl,
      connected ? '1' : '0',
      execOn ? '1' : '0',
      riskDesk.config.partitionUsd,
      riskDesk.config.shortPartitionPct,
      riskDesk.config.long1PartitionPct,
      riskDesk.config.long2PartitionPct,
      riskDesk.config.emergencyStop ? '1' : '0',
      riskDesk.config.pauseNewTrades ? '1' : '0',
      Math.round(riskDesk.metrics.dailyLossPct * 10),
      Math.round(riskDesk.metrics.drawdownPct * 10),
    ].join('|');
    if (syncKey === lastSyncKeyRef.current) return;
    lastSyncKeyRef.current = syncKey;

    const r = await syncScannerBridgeState(
      baseUrl,
      { config: riskDesk.config, metrics: riskDesk.metrics, positions, connected },
      { retries: connected ? 5 : 1, delayMs: 700 },
    );
    if (!r.ok) {
      lastSyncKeyRef.current = '';
      console.warn('[desk] scanner risk sync failed', r.exec?.error || r.risk?.error || r);
    }
  }, [baseUrl, connected, positions, riskDesk.config, riskDesk.hydrated, riskDesk.metrics]);

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
    if (!baseUrl?.trim() || !connected) return undefined;
    lastSyncKeyRef.current = '';
    void enableScannerAutoExecOnConnect(baseUrl);
    return undefined;
  }, [baseUrl, connected, sessionEpoch]);

  useEffect(() => {
    if (!baseUrl?.trim() || !connected || !riskDesk.hydrated) return undefined;
    lastSyncKeyRef.current = '';
    void syncScannerRisk();
    const boostEnd = Date.now() + CONNECT_EXEC_BOOST_DURATION_MS;
    const boostId = setInterval(() => {
      if (Date.now() > boostEnd) {
        clearInterval(boostId);
        return;
      }
      lastSyncKeyRef.current = '';
      void syncScannerRisk();
    }, CONNECT_EXEC_BOOST_MS);
    return () => clearInterval(boostId);
  }, [baseUrl, connected, sessionEpoch, riskDesk.hydrated, syncScannerRisk]);

  useEffect(() => {
    if (!baseUrl?.trim() || !riskDesk.hydrated || !connected) return undefined;
    lastSyncKeyRef.current = '';
    void syncScannerRisk();
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
    riskDesk.config.emergencyStop,
    riskDesk.config.pauseNewTrades,
    riskDesk.config.partitionUsd,
    riskDesk.config.shortPartitionPct,
    riskDesk.config.long1PartitionPct,
    riskDesk.config.long2PartitionPct,
    riskDesk.metrics.dailyLossPct,
    riskDesk.metrics.drawdownPct,
    riskDesk.metrics.weeklyLossPct,
    positions.length,
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
    effectiveAutoExecute,
  };
}
