import { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetchScannerSnapshot, subscribeScannerStream } from '../broker/binanceScannerApi';

const CACHE_KEY = '@bilshenz_v1/scannerSnapshotCache';
const CACHE_TTL_MS = 90_000;
const WS_STALE_MS = 5000;
const REST_POLL_MS = 5000;

function applyPayload(setters, payload) {
  if (!payload) return;
  if (payload.scanner) setters.setScannerMeta(payload.scanner);
  setters.setReady(true);
  setters.setError('');
  if (Array.isArray(payload.rows)) setters.setRows(payload.rows);
  if (payload.ts) setters.setLastTs(payload.ts);
  if (Array.isArray(payload.signals)) setters.setSignals(payload.signals);
  if (Array.isArray(payload.blocks)) setters.setBlocks(payload.blocks);
  if (Array.isArray(payload.execution_events)) setters.setExecutionEvents(payload.execution_events);
  if (Array.isArray(payload.scanner?.execution_events)) {
    setters.setExecutionEvents(payload.scanner.execution_events);
  }
}

async function readSnapshotCache() {
  try {
    const raw = await AsyncStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.rows?.length || Date.now() - (parsed.ts || 0) > CACHE_TTL_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function writeSnapshotCache(payload) {
  if (!payload?.rows?.length) return;
  try {
    await AsyncStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        ts: payload.ts || Date.now(),
        rows: payload.rows,
        scanner: payload.scanner,
        signals: payload.signals,
        blocks: payload.blocks,
        execution_events: payload.execution_events || payload.scanner?.execution_events,
      }),
    );
  } catch {
    /* ignore */
  }
}

/**
 * Live tick momentum scanner feed — WebSocket primary, always-on REST fallback when WS stale.
 */
export function useTickScanner(baseUrl, { enabled = true, sessionEpoch = 0, connected = false } = {}) {
  const [rows, setRows] = useState([]);
  const [signals, setSignals] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [executionEvents, setExecutionEvents] = useState([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [scannerMeta, setScannerMeta] = useState(null);
  const [lastTs, setLastTs] = useState(0);
  const lastWsAtRef = useRef(0);
  const pollBusyRef = useRef(false);

  const apply = useCallback((payload) => {
    applyPayload(
      { setRows, setReady, setError, setLastTs, setScannerMeta, setSignals, setBlocks, setExecutionEvents },
      payload,
    );
    void writeSnapshotCache(payload);
  }, []);

  const refresh = useCallback(async () => {
    if (!baseUrl?.trim()) return;
    const snap = await fetchScannerSnapshot(baseUrl, 5000);
    if (snap.ok) apply(snap);
  }, [baseUrl, apply]);

  useEffect(() => {
    if (!enabled || !baseUrl?.trim()) {
      setRows([]);
      setSignals([]);
      setBlocks([]);
      setExecutionEvents([]);
      setReady(false);
      return undefined;
    }

    let cancelled = false;
    lastWsAtRef.current = 0;

    const pollRest = async (force = false) => {
      if (cancelled || pollBusyRef.current) return;
      const wsFresh = lastWsAtRef.current > 0 && Date.now() - lastWsAtRef.current < WS_STALE_MS;
      if (!force && wsFresh) return;
      pollBusyRef.current = true;
      try {
        const snap = await fetchScannerSnapshot(baseUrl, 4000);
        if (!cancelled && snap.ok) apply(snap);
      } finally {
        pollBusyRef.current = false;
      }
    };

    void (async () => {
      const cached = await readSnapshotCache();
      if (!cancelled && cached?.rows?.length) apply(cached);
      await pollRest(true);
    })();

    const unsub = subscribeScannerStream(
      baseUrl,
      (payload) => {
        lastWsAtRef.current = Date.now();
        apply(payload);
      },
      {
        onOpen: () => {
          lastWsAtRef.current = Date.now();
        },
        onError: () => {
          lastWsAtRef.current = 0;
          void pollRest(true);
        },
      },
    );

    const poll = setInterval(() => void pollRest(false), REST_POLL_MS);

    return () => {
      cancelled = true;
      unsub();
      clearInterval(poll);
    };
  }, [baseUrl, enabled, apply]);

  useEffect(() => {
    if (!enabled || !baseUrl?.trim() || !connected) return undefined;
    void refresh();
    return undefined;
  }, [baseUrl, connected, enabled, sessionEpoch, refresh]);

  return { rows, signals, blocks, executionEvents, ready, error, scannerMeta, lastTs, refresh };
}
