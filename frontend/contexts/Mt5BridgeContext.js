import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getMt5ApiUrl } from '../lib/envConfig';
import { getDefaultMt5ApiUrl, getMetroLanHost, isLocalhostApiUrl } from '../utils/mt5ApiUrl';
import { fetchMt5Connected } from '../broker/mt5PythonApi';

const STORAGE_MT5_BASE = '@bilshenz_v1/mt5ApiBaseUrl';
const STORAGE_MT5_CONNECTED = '@bilshenz_v1/mt5ApiConnected';

const Mt5BridgeContext = createContext(null);

function resolveProductionUrl(storedUrl) {
  const vpsUrl = getDefaultMt5ApiUrl();
  if (vpsUrl && !isLocalhostApiUrl(vpsUrl)) {
    if (!storedUrl || isLocalhostApiUrl(storedUrl)) return vpsUrl;
  }
  if (storedUrl) return storedUrl;
  const baked = getMt5ApiUrl();
  if (baked && !isLocalhostApiUrl(baked)) return baked;
  const metroLan = getMetroLanHost();
  const d = getDefaultMt5ApiUrl();
  if (metroLan && isLocalhostApiUrl(d)) return `http://${metroLan}:8765`;
  return d;
}

export function Mt5BridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => resolveProductionUrl(null));
  const [connected, setConnected] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, storedUrl], [, conn]] = await AsyncStorage.multiGet([
          STORAGE_MT5_BASE,
          STORAGE_MT5_CONNECTED,
        ]);
        if (cancelled) return;
        const resolvedUrl = resolveProductionUrl(storedUrl || null);
        setBaseUrlState(resolvedUrl);
        if (resolvedUrl !== storedUrl) {
          AsyncStorage.setItem(STORAGE_MT5_BASE, resolvedUrl).catch(() => {});
        }
        if (conn !== '1' || !resolvedUrl) {
          setConnected(false);
        } else {
          const ok = await fetchMt5Connected(resolvedUrl.replace(/\/$/, ''));
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
    AsyncStorage.setItem(STORAGE_MT5_BASE, v).catch(() => {});
  }, []);

  const markConnected = useCallback((isConnected) => {
    setConnected(!!isConnected);
    AsyncStorage.setItem(STORAGE_MT5_CONNECTED, isConnected ? '1' : '0').catch(() => {});
  }, []);

  useEffect(() => {
    if (!hydrated || !connected || !baseUrl) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const ok = await fetchMt5Connected(baseUrl);
        if (cancelled) return;
        if (!ok) markConnected(false);
      } catch {
        if (!cancelled) markConnected(false);
      }
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [hydrated, connected, baseUrl, markConnected]);

  const value = useMemo(
    () => ({
      baseUrl,
      setBaseUrl,
      connected,
      setConnected: markConnected,
      hydrated,
    }),
    [baseUrl, setBaseUrl, connected, markConnected, hydrated],
  );

  return <Mt5BridgeContext.Provider value={value}>{children}</Mt5BridgeContext.Provider>;
}

export function useMt5Bridge() {
  const ctx = useContext(Mt5BridgeContext);
  if (!ctx) throw new Error('useMt5Bridge must be used within Mt5BridgeProvider');
  return ctx;
}
