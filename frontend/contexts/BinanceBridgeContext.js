import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getBinanceApiUrl } from '../lib/envConfig';
import { fetchBinanceSession, pickReachableBinanceBridgeUrl, binanceFetch } from '../broker/binanceFuturesApi';
import { getDefaultBinanceBridgeUrl, resolveBridgeUrlForDevice } from '../utils/binanceApiUrl';
import { isLocalhostApiUrl } from '../utils/bridgeLanUrl';
import { getBrokerMode } from '../lib/brokerMode';
import { tryBinanceSessionConnect } from '../lib/binanceSession';

const BinanceBridgeContext = createContext(null);

const STORAGE_BINANCE_BASE = '@bilshenz_v1/binanceApiBaseUrl';
const STORAGE_BINANCE_CONNECTED = '@bilshenz_v1/binanceApiConnected';
const STORAGE_BINANCE_URL_REV = '@bilshenz_v1/binanceApiUrlRev';
const BINANCE_URL_REV = '3';

function canonicalBinanceUrl() {
  const u = getBinanceApiUrl();
  if (u && !isLocalhostApiUrl(u)) return u.replace(/\/$/, '');
  return resolveBridgeUrlForDevice(getDefaultBinanceBridgeUrl());
}

export function BinanceBridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => canonicalBinanceUrl());
  const [connected, setConnected] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, storedUrl], [, conn], [, urlRev]] = await AsyncStorage.multiGet([
          STORAGE_BINANCE_BASE,
          STORAGE_BINANCE_CONNECTED,
          STORAGE_BINANCE_URL_REV,
        ]);
        if (cancelled) return;

        let resolved = canonicalBinanceUrl();
        if (storedUrl && urlRev === BINANCE_URL_REV && !isLocalhostApiUrl(storedUrl)) {
          resolved = storedUrl.replace(/\/$/, '');
        } else if (storedUrl && isLocalhostApiUrl(storedUrl)) {
          resolved = resolveBridgeUrlForDevice();
        }

        try {
          const health = await binanceFetch(resolved, '/health', {}, 3500);
          if (!health.ok) {
            const reachable = await pickReachableBinanceBridgeUrl(resolved);
            if (reachable) resolved = reachable;
          }
        } catch {
          const reachable = await pickReachableBinanceBridgeUrl(resolved);
          if (reachable) resolved = reachable;
        }

        setBaseUrlState(resolved);
        await AsyncStorage.multiSet([
          [STORAGE_BINANCE_BASE, resolved],
          [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
        ]);

        const session = await fetchBinanceSession(resolved, 5000, 0);
        if (session.ok) {
          if (!cancelled) {
            setConnected(true);
            await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '1');
          }
          if (!cancelled) setHydrated(true);
          return;
        }

        if (!cancelled) setHydrated(true);

        const hadSession = conn === '1';
        const shouldRestore = hadSession || getBrokerMode() === 'paper';
        if (!shouldRestore || cancelled) return;

        const restored = await tryBinanceSessionConnect(resolved, 12000);
        if (cancelled) return;
        if (restored.ok) {
          setBaseUrlState(restored.url);
          await AsyncStorage.multiSet([
            [STORAGE_BINANCE_BASE, restored.url],
            [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
            [STORAGE_BINANCE_CONNECTED, '1'],
          ]);
          setConnected(true);
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setHydrated(true);
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
    AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, isConnected ? '1' : '0').catch(() => {});
  }, []);

  useEffect(() => {
    if (!hydrated || !connected || !baseUrl) return;
    let cancelled = false;
    let failStreak = 0;
    const tick = async () => {
      const session = await fetchBinanceSession(baseUrl, 8000, 0);
      if (cancelled) return;
      if (session.ok) {
        failStreak = 0;
        return;
      }
      if (session.error && /unauthorized|bridge auth/i.test(session.error)) {
        failStreak += 1;
      } else {
        /* transient network blip — do not count toward disconnect */
        return;
      }
      if (failStreak >= 8) markConnected(false);
    };
    const boot = setTimeout(tick, 120000);
    const id = setInterval(tick, 120000);
    return () => {
      cancelled = true;
      clearTimeout(boot);
      clearInterval(id);
    };
  }, [hydrated, connected, baseUrl, markConnected]);

  const value = useMemo(
    () => ({ baseUrl, setBaseUrl, connected, setConnected: markConnected, hydrated }),
    [baseUrl, setBaseUrl, connected, markConnected, hydrated],
  );

  return <BinanceBridgeContext.Provider value={value}>{children}</BinanceBridgeContext.Provider>;
}

export function useBinanceBridge() {
  const ctx = useContext(BinanceBridgeContext);
  if (!ctx) throw new Error('useBinanceBridge must be used within BinanceBridgeProvider');
  return ctx;
}
