/** Scanner execution queue helpers — Watching / Pending short entries. */

export const RETRACE_ENTRY_PCT = 0.7;
export const GAIN_THRESHOLD_PCT = 5.0;

const STATUS_RANK = {
  Pending: 0,
  Watching: 1,
  Short: 2,
  Long1: 3,
  Long2: 4,
};

const QUEUE_STATUSES = new Set(['Watching', 'Pending']);

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
    return `Retrace ${Number(row.retracePct ?? 0).toFixed(2)}% ≥ ${RETRACE_ENTRY_PCT}% — armed for short entry`;
  }
  if (row.status === 'Watching') {
    const retrace = Number(row.retracePct ?? 0);
    const need = Math.max(0, RETRACE_ENTRY_PCT - retrace);
    return `+${Number(row.pctGain ?? 0).toFixed(2)}% on ${row.timeframe || 'tick'} — waiting ${need.toFixed(2)}% more retrace`;
  }
  return '';
}
