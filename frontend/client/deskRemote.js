import { deskApiHeaders, getDeskApiBase } from '../security/deskMode';

/**
 * @param {object} body
 * @returns {Promise<object>}
 */
export async function fetchDeskSnapshot(body) {
  const base = getDeskApiBase().replace(/\/$/, '');
  const res = await fetch(`${base}/v1/desk/compute`, {
    method: 'POST',
    headers: deskApiHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`Desk API ${res.status}: ${txt.slice(0, 120)}`);
  }
  return res.json();
}

/**
 * @param {object} body
 * @returns {Promise<{ ok: boolean, reason?: string }>}
 */
export async function fetchExecuteGate(body) {
  const base = getDeskApiBase().replace(/\/$/, '');
  const res = await fetch(`${base}/v1/desk/execute-gate`, {
    method: 'POST',
    headers: deskApiHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    return { ok: false, reason: 'API_ERROR' };
  }
  return res.json();
}
