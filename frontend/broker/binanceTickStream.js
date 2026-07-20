/**
 * Binance bridge WebSocket tick stream — replaces REST polling when available.
 */
import { getBridgeToken, getDeskApiKey } from '../lib/envConfig';
import { resetWsBackoff, scheduleWsReconnect } from '../lib/wsReconnect';

function wsBase(httpBase) {
  return String(httpBase || '')
    .replace(/\/$/, '')
    .replace(/^http:\/\//i, 'ws://')
    .replace(/^https:\/\//i, 'wss://');
}

/** Build authenticated WebSocket URL for bridge tick stream. */
export function binanceTickWsUrl(baseUrl, symbol) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  const wsRoot = wsBase(b);
  const path = b.includes('/v1/binance')
    ? `${wsRoot}/ws/tick/${encodeURIComponent(symbol)}`
    : `${wsRoot}/ws/tick/${encodeURIComponent(symbol)}`;
  const viaDesk = b.includes('/v1/binance');
  const token = viaDesk ? getDeskApiKey() : getBridgeToken();
  if (!token) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}token=${encodeURIComponent(token)}`;
}

/**
 * Subscribe to live ticks. Calls onTick on each message; returns cleanup function.
 * Reconnects immediately on drop, then fast capped backoff.
 */
export function subscribeBinanceTickStream(baseUrl, symbol, onTick, { onError, onOpen, onClose } = {}) {
  if (!baseUrl?.trim() || !symbol || typeof WebSocket === 'undefined') {
    return () => {};
  }

  let ws = null;
  let closed = false;
  const timerRef = { current: null };
  const backoffRef = { current: 0 };

  const isClosed = () => closed;

  const connect = () => {
    if (closed) return;
    const url = binanceTickWsUrl(baseUrl, symbol);
    try {
      ws = new WebSocket(url);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : String(e));
      scheduleWsReconnect({ closed: isClosed, timerRef, backoffRef, connect, immediate: true });
      return;
    }

    ws.onopen = () => {
      resetWsBackoff(backoffRef);
      onOpen?.();
    };

    ws.onmessage = (ev) => {
      try {
        const tk = JSON.parse(String(ev.data ?? ''));
        if (tk && Number.isFinite(tk.bid) && Number.isFinite(tk.ask)) {
          resetWsBackoff(backoffRef);
          onTick(tk);
        }
      } catch {
        /* ignore malformed */
      }
    };

    ws.onerror = () => {
      onError?.('WebSocket error');
    };

    ws.onclose = () => {
      ws = null;
      onError?.('WebSocket closed');
      onClose?.();
      if (!closed) {
        scheduleWsReconnect({ closed: isClosed, timerRef, backoffRef, connect, immediate: true });
      }
    };
  };

  connect();

  return () => {
    closed = true;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
    ws = null;
  };
}
