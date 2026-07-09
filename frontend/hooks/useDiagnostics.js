import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchBinanceDiagnostics } from '../broker/binanceFuturesApi';

/** Poll live VPS/Binance diagnostics — pauses when tab inactive. */
export function useDiagnostics(baseUrl, { enabled = true, intervalMs = 12000 } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (!enabled || !baseUrl?.trim()) return;
    setLoading(true);
    try {
      const j = await fetchBinanceDiagnostics(baseUrl);
      if (mounted.current) setData(j);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [baseUrl, enabled]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled || !baseUrl?.trim()) return undefined;
    void refresh();
    const id = setInterval(() => void refresh(), intervalMs);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [baseUrl, enabled, intervalMs, refresh]);

  return { diagnostics: data, loading, refresh };
}
