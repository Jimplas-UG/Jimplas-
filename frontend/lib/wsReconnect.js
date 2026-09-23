/**
 * Super-fast WebSocket reconnect — instant first retry, hard-capped backoff.
 */

export const WS_RECONNECT_MIN_MS = 40;
export const WS_RECONNECT_MAX_MS = 750;
export const WS_RECONNECT_FACTOR = 1.35;
/** Force-close + reconnect if no frames (incl. hb) arrive within this window. */
export const WS_SILENCE_MS = 3500;

export function jitterMs(ms) {
  if (ms <= 0) return 0;
  const spread = Math.round(ms * 0.1 * (Math.random() * 2 - 1));
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
  // First drop after a live session → instant; flapping → short capped backoff.
  const first = !backoffRef.current || backoffRef.current <= 0;
  const delay = immediate && first ? 0 : jitterMs(backoffRef.current || WS_RECONNECT_MIN_MS);
  timerRef.current = setTimeout(() => {
    timerRef.current = null;
    backoffRef.current = nextBackoffMs(backoffRef.current);
    connect();
  }, delay);
}

export function resetWsBackoff(backoffRef) {
  backoffRef.current = 0;
}

/**
 * Watch for zombie sockets (TCP half-open). Calls onSilent when no frames for WS_SILENCE_MS.
 * @returns {() => void} cleanup
 */
export function startWsSilenceWatch({ getWs, closed, onSilent, silenceMs = WS_SILENCE_MS }) {
  let lastMsgAt = Date.now();
  const mark = () => {
    lastMsgAt = Date.now();
  };
  const id = setInterval(() => {
    if (closed()) return;
    const ws = getWs?.();
    if (!ws || ws.readyState !== 1) return; // OPEN
    if (Date.now() - lastMsgAt >= silenceMs) {
      lastMsgAt = Date.now();
      onSilent?.();
    }
  }, Math.min(1000, Math.max(250, Math.floor(silenceMs / 3))));
  return { mark, stop: () => clearInterval(id) };
}
