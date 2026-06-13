import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getBinanceApiUrl } from '../lib/envConfig';
import { getDefaultBinanceApiUrl } from '../broker/binanceFuturesApi';
import { fetchBinanceConnected, postBinanceAttach, probeBinanceBridge } from '../broker/binanceFuturesApi';
import { isLocalhostApiUrl } from '../utils/mt5ApiUrl';

const BinanceBridgeContext = createContext(null);

const STORAGE_BINANCE_BASE = '@bilshenz_v1/binanceApiBaseUrl';
const STORAGE_BINANCE_CONNECTED = '@bilshenz_v1/binanceApiConnected';
const STORAGE_BINANCE_URL_REV = '@bilshenz_v1/binanceApiUrlRev';
const BINANCE_URL_REV = '1';

function canonicalVpsBinanceUrl() {
  const u = getBinanceApiUrl();
  if (u && !isLocalhostApiUrl(u)) return u.replace(/\/$/, '');
  return getDefaultBinanceApiUrl();
}

export function BinanceBridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => canonicalVpsBinanceUrl());
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
        const resolved = storedUrl && urlRev === BINANCE_URL_REV ? storedUrl.replace(/\/$/, '') : canonicalVpsBinanceUrl();
        setBaseUrlState(resolved);
        await AsyncStorage.multiSet([
          [STORAGE_BINANCE_BASE, resolved],
          [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
        ]);
        if (resolved) {
          let ok = await probeBinanceBridge(resolved, 3);
          if (!ok) {
            const attach = await postBinanceAttach(resolved, 20000);
            if (attach.ok) ok = true;
          }
          if (!cancelled) setConnected(!!ok);
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
    const tick = async () => {
      const ok = await fetchBinanceConnected(baseUrl, 8000);
      if (!cancelled && !ok) markConnected(false);
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => {
      cancelled = true;
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
