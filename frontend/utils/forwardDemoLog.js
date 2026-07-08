/**
 * Forward-demo execution log — POST to desk-api when EXPO_PUBLIC_DESK_API_URL is set.
 */
function deskBase() {
  const u = (process.env.EXPO_PUBLIC_DESK_API_URL || '').trim().replace(/\/$/, '');
  return u || null;
}

export async function logForwardDemoEvent(event) {
  const base = deskBase();
  if (!base) return;
  const now = Date.now();
  try {
    await fetch(`${base}/v1/validation/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ts: new Date(now).toISOString(),
        tsMs: now,
        symbol: 'BTCUSDT',
        ...event,
      }),
    });
  } catch {
    /* offline desk */
  }
}

export function logForwardSignal({ side, entry, sl, tp, setup, barTimeMs }) {
  return logForwardDemoEvent({
    type: 'SIGNAL',
    side,
    setup: setup || null,
    signalTsMs: barTimeMs,
    intendedEntry: entry,
    intendedSl: sl,
    intendedTp: tp,
  });
}

export function logForwardMissed({ reason, barTimeMs }) {
  return logForwardDemoEvent({
    type: 'MISSED_TRADE',
    missed: true,
    missReason: reason,
    signalTsMs: barTimeMs,
  });
}
