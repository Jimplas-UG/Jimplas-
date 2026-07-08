import { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetchScannerSnapshot, subscribeScannerStream } from '../broker/binanceScannerApi';

const CACHE_KEY = '@bilshenz_v1/scannerSnapshotCache';
const CACHE_TTL_MS = 90_000;

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
 * Live tick momentum scanner feed — WebSocket primary, REST bootstrap + reconnect fallback.
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
  const booted = useRef(false);

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
    if (snap.ok) {
      booted.current = true;
      apply(snap);
    }
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
    booted.current = false;

    void (async () => {
      const cached = await readSnapshotCache();
      if (!cancelled && cached?.rows?.length) {
        apply(cached);
        booted.current = true;
      }
      const snap = await fetchScannerSnapshot(baseUrl, 5000);
      if (cancelled) return;
      if (snap.ok) {
        apply(snap);
        booted.current = true;
      } else if (!booted.current) {
        setError(snap.error || 'Scanner unavailable');
      }
    })();

    const unsub = subscribeScannerStream(
      baseUrl,
      (payload) => {
        booted.current = true;
        apply(payload);
      },
      {
        onError: (msg) => {
          if (!booted.current) setError(msg || 'Scanner WS error');
        },
      },
    );

    const poll = setInterval(() => {
      if (booted.current) return;
      void fetchScannerSnapshot(baseUrl, 4000).then((snap) => {
        if (!cancelled && snap.ok) apply(snap);
      });
    }, 4000);

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
