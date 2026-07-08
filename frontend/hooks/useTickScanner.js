import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchScannerSnapshot, subscribeScannerStream } from '../broker/binanceScannerApi';

function applyPayload(setters, payload) {
  if (!payload) return;
  if (payload.scanner) setters.setScannerMeta(payload.scanner);
  // First successful snapshot means the engine is live — don't block UI on empty movers.
  setters.setReady(true);
  setters.setError('');
  if (Array.isArray(payload.rows)) setters.setRows(payload.rows);
  if (payload.ts) setters.setLastTs(payload.ts);
  if (Array.isArray(payload.signals)) setters.setSignals(payload.signals);
  if (Array.isArray(payload.blocks)) setters.setBlocks(payload.blocks);
}

/**
 * Live tick momentum scanner feed — WebSocket primary, REST bootstrap + reconnect fallback.
 * Pass sessionEpoch from BinanceBridgeContext to refresh exec state immediately after login.
 */
export function useTickScanner(baseUrl, { enabled = true, sessionEpoch = 0, connected = false } = {}) {
  const [rows, setRows] = useState([]);
  const [signals, setSignals] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [scannerMeta, setScannerMeta] = useState(null);
  const [lastTs, setLastTs] = useState(0);
  const booted = useRef(false);

  const apply = useCallback((payload) => {
    applyPayload(
      { setRows, setReady, setError, setLastTs, setScannerMeta, setSignals, setBlocks },
      payload,
    );
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
      setReady(false);
      return undefined;
    }

    let cancelled = false;
    booted.current = false;

    void (async () => {
      const snap = await fetchScannerSnapshot(baseUrl, 5000);
      if (cancelled) return;
      if (snap.ok) {
        apply(snap);
        booted.current = true;
      } else if (!snap.ok) {
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
        onOpen: () => {
          void fetchScannerSnapshot(baseUrl, 4000).then((snap) => {
            if (!cancelled && snap.ok) {
              booted.current = true;
              apply(snap);
            }
          });
        },
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
    }, 3000);

    return () => {
      cancelled = true;
      unsub();
      clearInterval(poll);
    };
  }, [baseUrl, enabled, apply]);

  // Binance linked — pull fresh exec/session state without waiting for next tick broadcast.
  useEffect(() => {
    if (!enabled || !baseUrl?.trim() || !connected) return undefined;
    void refresh();
    const id = setInterval(() => void refresh(), 2000);
    const stop = setTimeout(() => clearInterval(id), 8000);
    return () => {
      clearInterval(id);
      clearTimeout(stop);
    };
  }, [baseUrl, connected, enabled, sessionEpoch, refresh]);

  return { rows, signals, blocks, ready, error, scannerMeta, lastTs, refresh };
}
