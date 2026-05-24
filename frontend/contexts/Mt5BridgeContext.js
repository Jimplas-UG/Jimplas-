import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getDeskApiUrl, getMt5ApiUrl, isVpsDeployed } from '../lib/envConfig';
import { getDefaultMt5ApiUrl, getMetroLanHost, isLocalhostApiUrl } from '../utils/mt5ApiUrl';
import { fetchMt5Connected, postMt5Attach, probeMt5Bridge } from '../broker/mt5PythonApi';

const Mt5BridgeContext = createContext(null);

const STORAGE_MT5_BASE = '@bilshenz_v1/mt5ApiBaseUrl';
const STORAGE_MT5_CONNECTED = '@bilshenz_v1/mt5ApiConnected';
/** Bump when API URL scheme changes — forces migration off :8765 direct. */
const STORAGE_MT5_URL_REV = '@bilshenz_v1/mt5ApiUrlRev';
const MT5_URL_REV = '3';

function canonicalVpsMt5Url() {
  const u = getMt5ApiUrl();
  if (u && !isLocalhostApiUrl(u)) return u.replace(/\/$/, '');
  const desk = getDeskApiUrl();
  if (desk && !isLocalhostApiUrl(desk)) {
    return `${desk.replace(/\/$/, '')}/v1/mt5`;
  }
  return getDefaultMt5ApiUrl();
}

function mustMigrateStoredUrl(storedUrl, vpsUrl) {
  if (!vpsUrl || isLocalhostApiUrl(vpsUrl)) return false;
  if (!storedUrl) return true;
  if (isLocalhostApiUrl(storedUrl)) return true;
  if (/:8765(\/|$)/.test(storedUrl)) return true;
  if (vpsUrl.includes('/v1/mt5') && !storedUrl.includes('/v1/mt5')) return true;
  if (storedUrl.replace(/\/$/, '') !== vpsUrl.replace(/\/$/, '')) return true;
  return false;
}

function resolveProductionUrl(storedUrl, urlRev) {
  const vpsUrl = canonicalVpsMt5Url();
  const onVps = isVpsDeployed() || (vpsUrl && !isLocalhostApiUrl(vpsUrl));

  if (onVps && vpsUrl) {
    if (urlRev !== MT5_URL_REV || mustMigrateStoredUrl(storedUrl, vpsUrl)) {
      return vpsUrl;
    }
  }

  if (storedUrl && !mustMigrateStoredUrl(storedUrl, vpsUrl)) {
    return storedUrl.replace(/\/$/, '');
  }

  if (vpsUrl && !isLocalhostApiUrl(vpsUrl)) return vpsUrl;

  const metroLan = getMetroLanHost();
  const d = getDefaultMt5ApiUrl();
  if (metroLan && isLocalhostApiUrl(d)) return `http://${metroLan}:8765`;
  return d;
}

export function Mt5BridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => resolveProductionUrl(null, null));
  const [connected, setConnected] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, storedUrl], [, conn], [, urlRev]] = await AsyncStorage.multiGet([
          STORAGE_MT5_BASE,
          STORAGE_MT5_CONNECTED,
          STORAGE_MT5_URL_REV,
        ]);
        if (cancelled) return;
        const resolvedUrl = resolveProductionUrl(storedUrl || null, urlRev);
        setBaseUrlState(resolvedUrl);
        await AsyncStorage.multiSet([
          [STORAGE_MT5_BASE, resolvedUrl],
          [STORAGE_MT5_URL_REV, MT5_URL_REV],
        ]);
        if (!resolvedUrl) {
          setConnected(false);
        } else {
          let ok = await probeMt5Bridge(resolvedUrl, 3);
          if (!ok && (isVpsDeployed() || !isLocalhostApiUrl(resolvedUrl))) {
            const attach = await postMt5Attach(resolvedUrl, 20000);
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
      [STORAGE_MT5_BASE, v],
      [STORAGE_MT5_URL_REV, MT5_URL_REV],
    ]).catch(() => {});
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
        const ok = await probeMt5Bridge(baseUrl, 2);
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
