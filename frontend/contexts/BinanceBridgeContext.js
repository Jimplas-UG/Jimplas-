import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getBinanceApiUrl } from '../lib/envConfig';
import { fetchBinanceSession, pickReachableBinanceBridgeUrl, binanceFetch } from '../broker/binanceFuturesApi';
import { enableScannerAutoExecOnConnect } from '../lib/scannerRiskSync';
import { getDefaultBinanceBridgeUrl, resolveBridgeUrlForDevice } from '../utils/binanceApiUrl';
import { isLocalhostApiUrl } from '../utils/bridgeLanUrl';
import { getBrokerMode } from '../lib/brokerMode';
import { hasBinanceCredentials, isHardBinanceAuthFailure, loadStoredBinanceCredentials, restoreBinanceBridgeSession, tryBinanceSessionConnect } from '../lib/binanceSession';

const BinanceBridgeContext = createContext(null);

const STORAGE_BINANCE_BASE = '@bilshenz_v1/binanceApiBaseUrl';
const STORAGE_BINANCE_CONNECTED = '@bilshenz_v1/binanceApiConnected';
const STORAGE_BINANCE_URL_REV = '@bilshenz_v1/binanceApiUrlRev';
const BINANCE_URL_REV = '3';
const HEALTH_TIMEOUT_MS = 1500;
const RESTORE_TIMEOUT_MS = 4000;
const SESSION_TIMEOUT_MS = 2500;

function canonicalBinanceUrl() {
  const u = getBinanceApiUrl();
  if (u && !isLocalhostApiUrl(u)) return u.replace(/\/$/, '');
  return resolveBridgeUrlForDevice(getDefaultBinanceBridgeUrl());
}

function resolveStoredUrl(storedUrl, urlRev) {
  let resolved = canonicalBinanceUrl();
  if (storedUrl && urlRev === BINANCE_URL_REV && !isLocalhostApiUrl(storedUrl)) {
    resolved = storedUrl.replace(/\/$/, '');
  } else if (storedUrl && isLocalhostApiUrl(storedUrl)) {
    resolved = resolveBridgeUrlForDevice();
  }
  return resolved;
}

export function BinanceBridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => canonicalBinanceUrl());
  const [connected, setConnected] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [sessionEpoch, setSessionEpoch] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const probeInBackground = async (resolved, conn) => {
      let url = resolved;
      try {
        const health = await binanceFetch(url, '/health', {}, HEALTH_TIMEOUT_MS);
        if (!health.ok) {
          const reachable = await pickReachableBinanceBridgeUrl(url);
          if (reachable) url = reachable;
        }
      } catch {
        const reachable = await pickReachableBinanceBridgeUrl(url);
        if (reachable) url = reachable;
      }

      if (cancelled) return;
      if (url !== resolved) {
        setBaseUrlState(url);
        await AsyncStorage.multiSet([
          [STORAGE_BINANCE_BASE, url],
          [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
        ]);
      }

      const session = await fetchBinanceSession(url, SESSION_TIMEOUT_MS, 0);
      if (cancelled) return;
      if (session.ok) {
        const creds = await loadStoredBinanceCredentials();
        const mode = getBrokerMode();
        if (mode !== 'paper' && !hasBinanceCredentials(creds)) {
          await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '0');
          return;
        }
        setConnected(true);
        setSessionEpoch((n) => n + 1);
        await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '1');
        return;
      }

      const hadSession = conn === '1';
      const creds = await loadStoredBinanceCredentials();
      const mode = getBrokerMode();
      const canLogin = mode === 'paper' || hasBinanceCredentials(creds);
      const shouldRestore = canLogin && (hadSession || mode === 'paper');
      if (!shouldRestore) {
        if (hadSession && !canLogin) {
          await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '0');
        }
        return;
      }

      const restored = await tryBinanceSessionConnect(url, RESTORE_TIMEOUT_MS);
      if (cancelled || !restored.ok) return;
      setBaseUrlState(restored.url);
      await AsyncStorage.multiSet([
        [STORAGE_BINANCE_BASE, restored.url],
        [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
        [STORAGE_BINANCE_CONNECTED, '1'],
      ]);
      setConnected(true);
      setSessionEpoch((n) => n + 1);
    };

    (async () => {
      try {
        const [[, storedUrl], [, conn], [, urlRev]] = await AsyncStorage.multiGet([
          STORAGE_BINANCE_BASE,
          STORAGE_BINANCE_CONNECTED,
          STORAGE_BINANCE_URL_REV,
        ]);
        if (cancelled) return;

        const resolved = resolveStoredUrl(storedUrl, urlRev);
        setBaseUrlState(resolved);
        setHydrated(true);

        void probeInBackground(resolved, conn);
      } catch {
        if (!cancelled) {
          setBaseUrlState(canonicalBinanceUrl());
          setHydrated(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const setBaseUrl = useCallback((url) => {
    const v = String(url || '').replace(/\/$/, '');
    setBaseUrlState(v);
    AsyncStorage.multiSet([
      [STORAGE_BINANCE_BASE, v],
      [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
    ]).catch(() => {});
  }, []);

  const markConnected = useCallback((isConnected) => {
    setConnected(!!isConnected);
    if (isConnected) setSessionEpoch((n) => n + 1);
    AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, isConnected ? '1' : '0').catch(() => {});
  }, []);

  useEffect(() => {
    if (!baseUrl?.trim() || !connected) return undefined;
    void enableScannerAutoExecOnConnect(baseUrl, { retries: 3, delayMs: 400 });
    return undefined;
  }, [baseUrl, connected, sessionEpoch]);

  useEffect(() => {
    if (!hydrated || !connected || !baseUrl) return;
    let cancelled = false;
    const tick = async () => {
      const creds = await loadStoredBinanceCredentials();
      const mode = getBrokerMode();
      if (mode !== 'paper' && !hasBinanceCredentials(creds)) {
        markConnected(false);
        return;
      }

      const session = await fetchBinanceSession(baseUrl, 8000, 1);
      if (cancelled) return;
      if (session.ok) return;

      if (isHardBinanceAuthFailure(session.error)) {
        markConnected(false);
        return;
      }

      const restored = await restoreBinanceBridgeSession(baseUrl, 15000);
      if (cancelled) return;
      if (restored.ok && restored.session) {
        if (restored.url && restored.url !== baseUrl) setBaseUrlState(restored.url);
        markConnected(true);
        setSessionEpoch((n) => n + 1);
        return;
      }
      if (restored.hardFail) markConnected(false);
      /* transient failure — stay connected, retry on next tick */
    };
    const boot = setTimeout(tick, 60000);
    const id = setInterval(tick, 60000);
    return () => {
      cancelled = true;
      clearTimeout(boot);
      clearInterval(id);
    };
  }, [hydrated, connected, baseUrl, markConnected]);

  const value = useMemo(
    () => ({ baseUrl, setBaseUrl, connected, setConnected: markConnected, hydrated, sessionEpoch }),
    [baseUrl, setBaseUrl, connected, markConnected, hydrated, sessionEpoch],
  );

  return <BinanceBridgeContext.Provider value={value}>{children}</BinanceBridgeContext.Provider>;
}

export function useBinanceBridge() {
  const ctx = useContext(BinanceBridgeContext);
  if (!ctx) throw new Error('useBinanceBridge must be used within BinanceBridgeProvider');
  return ctx;
}
