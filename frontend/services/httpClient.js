/**
 * Resilient HTTP for desk-api — retries, timeout, no secret logging.
 */

const DEFAULT_TIMEOUT_MS = 12000;
const MAX_RETRIES = 3;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * @param {string} url
 * @param {RequestInit} init
 * @param {{ timeoutMs?: number, retries?: number }} [opts]
 */
export async function fetchWithRetry(url, init = {}, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const retries = opts.retries ?? MAX_RETRIES;
  let lastErr = null;

  for (let attempt = 0; attempt < retries; attempt++) {
    if (attempt > 0) await sleep(400 * attempt);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...init, signal: ctrl.signal });
      clearTimeout(timer);
      return res;
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      if (attempt === retries - 1) break;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}
