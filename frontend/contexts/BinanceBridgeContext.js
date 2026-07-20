import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getBinanceApiUrl } from '../lib/envConfig';
import { fetchBinanceSession, pickReachableBinanceBridgeUrl, binanceFetch } from '../broker/binanceFuturesApi';
import { getDefaultBinanceBridgeUrl, resolveBridgeUrlForDevice } from '../utils/binanceApiUrl';
import { isLocalhostApiUrl } from '../utils/bridgeLanUrl';
import { getBrokerMode } from '../lib/brokerMode';
import {
  hasBinanceCredentials,
  isHardBinanceAuthFailure,
  isTransientBridgeError,
  loadStoredBinanceCredentials,
  restoreBinanceBridgeSession,
  tryBinanceSessionConnect,
} from '../lib/binanceSession';

const BinanceBridgeContext = createContext(null);

const STORAGE_BINANCE_BASE = '@bilshenz_v1/binanceApiBaseUrl';
const STORAGE_BINANCE_CONNECTED = '@bilshenz_v1/binanceApiConnected';
const STORAGE_BINANCE_URL_REV = '@bilshenz_v1/binanceApiUrlRev';
const BINANCE_URL_REV = '3';
const HEALTH_TIMEOUT_MS = 600;
const RESTORE_TIMEOUT_MS = 3500;
const SESSION_TIMEOUT_MS = 1200;
const STABLE_WATCHDOG_MS = 60000;
const FAST_WATCHDOG_MS = 15000;
const CRED_CACHE_MS = 30000;

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

function execFromBridgeSession(session) {
  if (!session?.ok) {
    return { canExecute: false, block: session?.exec_block || session?.error || null };
  }
  const block = session.exec_block || null;
  const envHalt = block === 'SCANNER_EXEC=0' || block === 'FORWARD_DRY_RUN';
  const canExecute = !envHalt && session.can_execute !== false;
  return { canExecute, block };
}

export function BinanceBridgeProvider({ children }) {
  const [baseUrl, setBaseUrlState] = useState(() => canonicalBinanceUrl());
  const [connected, setConnected] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [sessionExec, setSessionExec] = useState({ canExecute: false, block: null });
  const credsCacheRef = useRef({ at: 0, creds: null, mode: null });
  const stableTicksRef = useRef(0);

  const getCachedCreds = useCallback(async () => {
    const now = Date.now();
    const mode = getBrokerMode();
    if (credsCacheRef.current.creds && credsCacheRef.current.mode === mode && now - credsCacheRef.current.at < CRED_CACHE_MS) {
      return credsCacheRef.current.creds;
    }
    const creds = await loadStoredBinanceCredentials();
    credsCacheRef.current = { at: now, creds, mode };
    return creds;
  }, []);

  useEffect(() => {
    let cancelled = false;

    const probeInBackground = async (resolved, conn) => {
      let url = resolved;

      let session = await fetchBinanceSession(url, SESSION_TIMEOUT_MS, 0);
      if (cancelled) return;

      if (!session.ok) {
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
          session = await fetchBinanceSession(url, SESSION_TIMEOUT_MS, 0);
          if (cancelled) return;
        }
      }

      if (session.ok) {
        setSessionExec(execFromBridgeSession(session));
        setConnected(true);
        setSessionEpoch((n) => n + 1);
        await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '1');
        return;
      }

      const creds = await getCachedCreds();
      const mode = getBrokerMode();
      const canLogin = mode === 'paper' || hasBinanceCredentials(creds);
      if (!canLogin) {
        if (conn === '1') {
          setConnected(false);
          await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '0');
        }
        return;
      }

      const restored = await tryBinanceSessionConnect(url, RESTORE_TIMEOUT_MS);
      if (cancelled) return;
      if (!restored.ok) {
        if (conn === '1' && isHardBinanceAuthFailure(restored.error)) {
          setConnected(false);
          await AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, '0');
        }
        return;
      }
      setBaseUrlState(restored.url);
      await AsyncStorage.multiSet([
        [STORAGE_BINANCE_BASE, restored.url],
        [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
        [STORAGE_BINANCE_CONNECTED, '1'],
      ]);
      setConnected(true);
      setSessionEpoch((n) => n + 1);
      if (restored.session) setSessionExec(execFromBridgeSession(restored.session));
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
        if (conn === '1') {
          setConnected(true);
          setSessionEpoch((n) => n + 1);
        }
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
  }, [getCachedCreds]);

  const setBaseUrl = useCallback((url) => {
    const v = String(url || '').replace(/\/$/, '');
    setBaseUrlState(v);
    AsyncStorage.multiSet([
      [STORAGE_BINANCE_BASE, v],
      [STORAGE_BINANCE_URL_REV, BINANCE_URL_REV],
    ]).catch(() => {});
    setSessionEpoch((n) => n + 1);
  }, []);

  const applyBridgeSession = useCallback((session) => {
    setSessionExec(execFromBridgeSession(session));
  }, []);

  const markConnected = useCallback((isConnected, session = null) => {
    setConnected(!!isConnected);
    if (isConnected) {
      if (session) setSessionExec(execFromBridgeSession(session));
      setSessionEpoch((n) => n + 1);
      stableTicksRef.current = 0;
    } else {
      setSessionExec({ canExecute: false, block: null });
      stableTicksRef.current = 0;
    }
    AsyncStorage.setItem(STORAGE_BINANCE_CONNECTED, isConnected ? '1' : '0').catch(() => {});
  }, []);

  useEffect(() => {
    if (!hydrated || !connected || !baseUrl) return;
    let cancelled = false;
    let timer = null;
    let failStreak = 0;

    const scheduleNext = (delayMs) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void tick(), delayMs);
    };

    const tick = async () => {
      const creds = await getCachedCreds();
      const mode = getBrokerMode();
      if (mode !== 'paper' && !hasBinanceCredentials(creds)) {
        markConnected(false);
        return;
      }

      const session = await fetchBinanceSession(baseUrl, 4000, 0);
      if (cancelled) return;
      if (session.ok) {
        failStreak = 0;
        stableTicksRef.current += 1;
        setSessionExec(execFromBridgeSession(session));
        scheduleNext(stableTicksRef.current >= 3 ? STABLE_WATCHDOG_MS : FAST_WATCHDOG_MS);
        return;
      }

      if (isHardBinanceAuthFailure(session.error)) {
        markConnected(false);
        return;
      }

      failStreak += 1;
      if (failStreak === 1 && isTransientBridgeError(session.error)) {
        await new Promise((r) => setTimeout(r, 400));
        const retry = await fetchBinanceSession(baseUrl, 4000, 0);
        if (cancelled) return;
        if (retry.ok) {
          failStreak = 0;
          stableTicksRef.current += 1;
          setSessionExec(execFromBridgeSession(retry));
          scheduleNext(stableTicksRef.current >= 3 ? STABLE_WATCHDOG_MS : FAST_WATCHDOG_MS);
          return;
        }
      }

      if (failStreak >= 2) {
        const restored = await restoreBinanceBridgeSession(baseUrl, 12000);
        if (cancelled) return;
        if (restored.ok && restored.session) {
          failStreak = 0;
          stableTicksRef.current = 0;
          if (restored.url && restored.url !== baseUrl) setBaseUrlState(restored.url);
          markConnected(true, restored.session);
          scheduleNext(FAST_WATCHDOG_MS);
          return;
        }
        if (restored.hardFail) markConnected(false);
      }

      scheduleNext(FAST_WATCHDOG_MS);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [hydrated, connected, baseUrl, markConnected, getCachedCreds]);

  const value = useMemo(
    () => ({
      baseUrl,
      setBaseUrl,
      connected,
      setConnected: markConnected,
      applyBridgeSession,
      sessionExec,
      hydrated,
      sessionEpoch,
    }),
    [baseUrl, setBaseUrl, connected, markConnected, applyBridgeSession, sessionExec, hydrated, sessionEpoch],
  );

  return <BinanceBridgeContext.Provider value={value}>{children}</BinanceBridgeContext.Provider>;
}

export function useBinanceBridge() {
  const ctx = useContext(BinanceBridgeContext);
  if (!ctx) throw new Error('useBinanceBridge must be used within BinanceBridgeProvider');
  return ctx;
}
