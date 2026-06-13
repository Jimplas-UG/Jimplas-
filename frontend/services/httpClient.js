/**
 * Resilient HTTP for desk-api — retries, timeout, no secret logging.
 */
import { useMockApi } from '../lib/devPreview';
import { tryMockFetch } from '../mocks/mockApi';

const DEFAULT_TIMEOUT_MS = 12000;
const MAX_RETRIES = 3;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchMaybeMock(url, init) {
  if (useMockApi()) {
    const mock = tryMockFetch(url, init);
    if (mock) return mock;
  }
  return fetch(url, init);
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
      const res = await fetchMaybeMock(url, { ...init, signal: ctrl.signal });
      clearTimeout(timer);
      return res;
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      if (useMockApi()) {
        const mock = tryMockFetch(url, init);
        if (mock) return mock;
      }
      if (attempt === retries - 1) break;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}
