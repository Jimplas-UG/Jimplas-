import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchScannerSnapshot, subscribeScannerStream } from '../broker/binanceScannerApi';

function applyPayload(setters, payload) {
  if (!payload?.rows) return;
  setters.setRows(payload.rows);
  setters.setReady(true);
  setters.setError('');
  if (payload.ts) setters.setLastTs(payload.ts);
  if (payload.scanner) setters.setScannerMeta(payload.scanner);
  if (Array.isArray(payload.signals)) setters.setSignals(payload.signals);
  if (Array.isArray(payload.blocks)) setters.setBlocks(payload.blocks);
}

/**
 * Live tick momentum scanner feed — WebSocket primary, REST bootstrap + reconnect fallback.
 */
export function useTickScanner(baseUrl, { enabled = true } = {}) {
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
      const snap = await fetchScannerSnapshot(baseUrl);
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
          if (!booted.current) {
            void fetchScannerSnapshot(baseUrl).then((snap) => {
              if (!cancelled && snap.ok) apply(snap);
            });
          }
        },
        onError: (msg) => {
          if (!booted.current) setError(msg || 'Scanner WS error');
        },
      },
    );

    const poll = setInterval(() => {
      if (booted.current) return;
      void fetchScannerSnapshot(baseUrl).then((snap) => {
        if (!cancelled && snap.ok) apply(snap);
      });
    }, 8000);

    return () => {
      cancelled = true;
      unsub();
      clearInterval(poll);
    };
  }, [baseUrl, enabled, apply]);

  const refresh = useCallback(async () => {
    if (!baseUrl?.trim()) return;
    const snap = await fetchScannerSnapshot(baseUrl);
    if (snap.ok) apply(snap);
  }, [baseUrl, apply]);

  return { rows, signals, blocks, ready, error, scannerMeta, lastTs, refresh };
}
