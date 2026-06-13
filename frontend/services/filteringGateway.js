/**
 * Server-validated filtering — execution decisions only from desk-api in production.
 */
import { fetchWithRetry } from './httpClient';
import { deskApiHeaders, getDeskApiBase, IS_PRODUCTION_DESK, USE_REMOTE_DESK } from '../security/deskMode';
import { useMockApi } from '../lib/devPreview';
import { mockExecuteGate } from '../mocks/mockApi';

const inflightGates = new Map();

/**
 * @param {object|null} gateBody from engine hook
 * @param {{ runMode?: string }} [ctx]
 * @returns {Promise<{ ok: boolean, reason?: string }>}
 */
export async function validateExecutionGate(gateBody, ctx = {}) {
  if (!gateBody) return { ok: false, reason: 'NO_CONTEXT' };
  if (ctx.runMode === 'backtest') return { ok: false, reason: 'BACKTEST' };
  if (useMockApi()) return mockExecuteGate();

  if (!USE_REMOTE_DESK) {
    if (IS_PRODUCTION_DESK) return { ok: false, reason: 'LOCAL_DISABLED' };
    const { canExecuteTrade } = await import('../broker/tradeExecutionGates');
    return canExecuteTrade(gateBody.snapshot, gateBody.trade);
  }

  const dedupeKey = gateBody.idempotencyKey ?? `${gateBody.barT ?? 0}:${gateBody.trade?.side ?? ''}`;
  if (inflightGates.has(dedupeKey)) return inflightGates.get(dedupeKey);

  const base = getDeskApiBase().replace(/\/$/, '');
  const p = fetchWithRetry(`${base}/v1/desk/execute-gate`, {
    method: 'POST',
    headers: deskApiHeaders(),
    body: JSON.stringify(gateBody),
  })
    .then(async (res) => {
      if (!res.ok) return { ok: false, reason: 'API_ERROR' };
      return res.json();
    })
    .catch(() => ({ ok: false, reason: IS_PRODUCTION_DESK ? 'API_DOWN' : 'OFFLINE' }))
    .finally(() => {
      inflightGates.delete(dedupeKey);
    });

  inflightGates.set(dedupeKey, p);
  return p;
}
