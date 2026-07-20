/**
 * Fast WebSocket reconnect — immediate first retry, capped backoff, jitter.
 */

export const WS_RECONNECT_MIN_MS = 200;
export const WS_RECONNECT_MAX_MS = 5000;
export const WS_RECONNECT_FACTOR = 1.5;

export function jitterMs(ms) {
  if (ms <= 0) return 0;
  const spread = Math.round(ms * 0.12 * (Math.random() * 2 - 1));
  return Math.max(0, ms + spread);
}

export function nextBackoffMs(current) {
  if (!current || current <= 0) return WS_RECONNECT_MIN_MS;
  return Math.min(WS_RECONNECT_MAX_MS, Math.round(current * WS_RECONNECT_FACTOR));
}

/**
 * @param {{ closed: () => boolean, timerRef: { current: number|null }, backoffRef: { current: number }, connect: () => void, immediate?: boolean }} opts
 */
export function scheduleWsReconnect({ closed, timerRef, backoffRef, connect, immediate = false }) {
  if (closed() || timerRef.current) return;
  const delay = immediate ? 0 : jitterMs(backoffRef.current || WS_RECONNECT_MIN_MS);
  timerRef.current = setTimeout(() => {
    timerRef.current = null;
    backoffRef.current = nextBackoffMs(backoffRef.current);
    connect();
  }, delay);
}

export function resetWsBackoff(backoffRef) {
  backoffRef.current = 0;
}
