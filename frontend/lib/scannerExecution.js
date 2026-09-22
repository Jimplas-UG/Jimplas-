/** Scanner execution queue helpers — Watching / Pending long entries. */

export const RETRACE_ENTRY_PCT = 0.7;
export const GAIN_THRESHOLD_PCT = 5.0;

/** Live trade statuses from the Python scanner (Long → Short 1 → Short 2). */
export const ACTIVE_TRADE_STATUSES = new Set(['Long', 'Short 1', 'Short 2']);

const STATUS_RANK = {
  Pending: 0,
  Watching: 1,
  Long: 2,
  'Short 1': 3,
  'Short 2': 4,
};

const QUEUE_STATUSES = new Set(['Watching', 'Pending']);

/** Normalize legacy scanner status strings for display and sorting. */
export function normalizeScannerStatus(status) {
  const s = String(status || '');
  if (s === 'Long 1' || s === 'Long1') return 'Long';
  if (s === 'Short' || s === 'SHORT') return 'Short 1';
  if (s === 'Long 2' || s === 'Long2') return 'Short 2';
  return s;
}

export function isActiveTradeStatus(status) {
  return ACTIVE_TRADE_STATUSES.has(normalizeScannerStatus(status));
}

export function isExecutionQueueStatus(status) {
  return QUEUE_STATUSES.has(String(status || ''));
}

export function pickExecutionCandidates(rows) {
  return (rows || [])
    .filter((r) => isExecutionQueueStatus(r.status))
    .sort((a, b) => {
      const ra = STATUS_RANK[a.status] ?? 9;
      const rb = STATUS_RANK[b.status] ?? 9;
      if (ra !== rb) return ra - rb;
      return Number(b.pctGain ?? 0) - Number(a.pctGain ?? 0);
    });
}

export function pickPrimaryExecutionCandidate(rows, scannerMeta) {
  const candidates = pickExecutionCandidates(rows);
  if (candidates.length) return candidates[0];
  const sym = scannerMeta?.best_pending || scannerMeta?.active_symbol;
  if (!sym) return null;
  return (rows || []).find((r) => r.symbol === sym) || null;
}

export function executionStatusHint(row) {
  if (!row) return '';
  if (row.status === 'Pending') {
    return `Retrace ${Number(row.retracePct ?? 0).toFixed(2)}% ≥ ${RETRACE_ENTRY_PCT}% — armed for long entry`;
  }
  if (row.status === 'Watching') {
    const retrace = Number(row.retracePct ?? 0);
    const need = Math.max(0, RETRACE_ENTRY_PCT - retrace);
    return `+${Number(row.pctGain ?? 0).toFixed(2)}% on ${row.timeframe || 'tick'} — waiting ${need.toFixed(2)}% more retrace`;
  }
  return '';
}

export function formatScannerStatus(status) {
  return normalizeScannerStatus(status);
}
