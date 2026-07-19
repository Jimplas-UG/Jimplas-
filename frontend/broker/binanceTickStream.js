/**
 * Binance bridge WebSocket tick stream — replaces REST polling when available.
 */
import { getBridgeToken, getDeskApiKey } from '../lib/envConfig';

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
 * Falls back gracefully — caller should keep REST poll as backup until first WS tick.
 */
export function subscribeBinanceTickStream(baseUrl, symbol, onTick, { onError, onOpen } = {}) {
  if (!baseUrl?.trim() || !symbol || typeof WebSocket === 'undefined') {
    return () => {};
  }

  let ws = null;
  let closed = false;
  let reconnectTimer = null;
  let backoffMs = 350;

  const connect = () => {
    if (closed) return;
    const url = binanceTickWsUrl(baseUrl, symbol);
    try {
      ws = new WebSocket(url);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : String(e));
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      backoffMs = 350;
      onOpen?.();
    };

    ws.onmessage = (ev) => {
      try {
        const tk = JSON.parse(String(ev.data ?? ''));
        if (tk && Number.isFinite(tk.bid) && Number.isFinite(tk.ask)) {
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
      if (!closed) scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      backoffMs = Math.min(30000, Math.round(backoffMs * 1.6));
      connect();
    }, backoffMs);
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
    ws = null;
  };
}
