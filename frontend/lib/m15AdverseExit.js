/** M15 half-loss exit (parity with backend/engine/m15AdverseExit.ts). */

export function slUsesPreviousM30Bar(row, m30) {
  const ei = row.barIndex;
  if (ei < 1 || ei >= m30.length) return false;
  const prev = m30[ei - 1];
  if (row.dir === 'BUY') return row.sl <= prev.l;
  return row.sl >= prev.h;
}

export function halfLossExitPrice(row) {
  if (row.dir === 'BUY') return row.entry - (row.entry - row.sl) * 0.5;
  return row.entry + (row.sl - row.entry) * 0.5;
}

export function isAdverseM15Close(row, m15Bar) {
  if (row.dir === 'BUY') {
    return m15Bar.c < m15Bar.o && m15Bar.c < row.entry;
  }
  return m15Bar.c > m15Bar.o && m15Bar.c > row.entry;
}

export function underwaterRiskFraction(row, price) {
  if (row.dir === 'BUY') {
    const risk = row.entry - row.sl;
    if (!(risk > 0)) return 0;
    const against = row.entry - price;
    return against > 0 ? against / risk : 0;
  }
  const risk = row.sl - row.entry;
  if (!(risk > 0)) return 0;
  const against = price - row.entry;
  return against > 0 ? against / risk : 0;
}

export function armM15ExitWatch(row, m30, cfg) {
  if (!cfg?.enableM15AdverseExit) return row;
  if (!slUsesPreviousM30Bar(row, m30)) return row;
  return {
    ...row,
    m15ExitWatch: true,
    m15CheckedThroughMs: m30[row.barIndex].t,
  };
}

export function applyM15AdverseExit(row, m15, m30, barIndex, cfg) {
  if (row.out !== 'OPEN' || !row.m15ExitWatch) return row;
  const M30_MS = 30 * 60 * 1000;
  const M15_MS = 15 * 60 * 1000;
  const entryMs = m30[row.barIndex].t;
  const afterMs = row.m15CheckedThroughMs ?? entryMs;
  const upToCloseMs = m30[barIndex].t + M30_MS;
  const window = m15.filter((b) => {
    const closeMs = b.t + M15_MS;
    return closeMs > afterMs && closeMs <= upToCloseMs;
  });
  let checkedThrough = afterMs;
  const minPct = cfg.m15MinRiskPctBeforeExit ?? 0.45;
  for (const m15b of window) {
    checkedThrough = m15b.t + M15_MS;
    const underwater = underwaterRiskFraction(row, m15b.c) >= minPct;
    if (isAdverseM15Close(row, m15b) && underwater) {
      return {
        ...row,
        out: 'HALF_LOSS',
        exitPrice: halfLossExitPrice(row),
        m15CheckedThroughMs: checkedThrough,
      };
    }
  }
  if (checkedThrough > afterMs) {
    return { ...row, m15CheckedThroughMs: checkedThrough };
  }
  return row;
}
