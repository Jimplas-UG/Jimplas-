/**
 * Strategy protection layer — all engine math stays on desk-api.
 * Client never receives raw rule definitions; only sanitized snapshots.
 */
import { fetchWithRetry } from './httpClient';
import { deskApiHeaders, getDeskApiBase, IS_PRODUCTION_DESK } from '../security/deskMode';
import { sanitizeSnapshot } from '../security/sanitizeDesk';
import { EMPTY_TRADE, ensureDeskSnapshot } from '../lib/snapshotDefaults';

let _snapshotCache = null;
let _snapshotCacheKey = '';
let _inflightSnapshot = null;

function cacheKey(body) {
  const m30 = body?.bundle?.m30;
  const last = m30?.length ? m30[m30.length - 1]?.t : 0;
  return `${last}:${body?.dailyTradeCount ?? 0}:${body?.nowUtcMs ?? 0}`;
}

/**
 * Server-side strategy compute — production never falls back to local engine.
 * @param {object} body
 * @returns {Promise<object>}
 */
export async function requestDeskSnapshot(body) {
  const key = cacheKey(body);
  if (_snapshotCache && _snapshotCacheKey === key) return _snapshotCache;

  if (_inflightSnapshot) return _inflightSnapshot;

  const base = getDeskApiBase().replace(/\/$/, '');
  _inflightSnapshot = fetchWithRetry(`${base}/v1/desk/compute`, {
    method: 'POST',
    headers: deskApiHeaders(),
    body: JSON.stringify(body),
  }, IS_PRODUCTION_DESK ? { timeoutMs: 5000, retries: 2 } : undefined)
    .then(async (res) => {
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(`DESK_${res.status}`);
      }
      return res.json();
    })
    .then((raw) => {
      const safe = sanitizeSnapshot(raw) ?? ensureDeskSnapshot(null);
      _snapshotCache = safe;
      _snapshotCacheKey = key;
      return safe;
    })
    .finally(() => {
      _inflightSnapshot = null;
    });

  return _inflightSnapshot;
}

/** Offline-safe display snapshot when API is down. */
export function offlineSnapshotFallback(prev) {
  if (prev) return prev;
  return ensureDeskSnapshot({
    trade: {
      ...EMPTY_TRADE,
      status: 'OFFLINE',
      statusLine: 'Desk API unavailable — reconnect',
      setupPill: '—',
    },
  });
}

export function clearStrategyCache() {
  _snapshotCache = null;
  _snapshotCacheKey = '';
}

if (IS_PRODUCTION_DESK) {
  Object.freeze(requestDeskSnapshot);
}
