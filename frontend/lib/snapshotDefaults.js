/** Defaults so UI never crashes when desk-api returns a partial snapshot. */

export const EMPTY_SIGNALS = {
  anyBuy: false,
  anySell: false,
  p1Buy: false,
  p1Sell: false,
  p2Buy: false,
  p2Sell: false,
  p3Buy: false,
  p3Sell: false,
};

export const EMPTY_WIN_RATE = {
  totalWins: 0,
  totalLosses: 0,
  winRatePct: 0,
  p1Wr: 0,
  p2Wr: 0,
  p3Wr: 0,
  journal: [],
};

export const EMPTY_TRADE = {
  allowed: false,
  side: null,
  setup: null,
  entry: null,
  sl: null,
  tp1: null,
  rr: null,
  confidencePct: 0,
  reason: '',
  blocks: [],
  status: 'WAIT',
  statusLine: 'Scanning market — no active signal',
};

export const EMPTY_SESSION = {
  preLondon: false,
  london: false,
  newYork: false,
  inSession: false,
  name: 'DEAD',
  sessionLabel: 'STANDBY',
};

export const EMPTY_RISK = {
  riskLevel: 'LOW',
  atrMode: '—',
  atrPips: null,
  chopZone: false,
  brokerSpreadBlocked: false,
  barRangeBlocked: false,
  spreadBlocked: false,
  dxyRising: false,
  dxyBlocksBuy: false,
  yieldHigh: false,
  athZoneBlocked: false,
  geoMedium: false,
  geoHigh: false,
};

/**
 * @param {object|null|undefined} snap
 * @param {object} [boot]
 */
export function ensureDeskSnapshot(snap, boot = {}) {
  if (!snap || typeof snap !== 'object') {
    return {
      ...boot,
      signals: { ...EMPTY_SIGNALS, ...(boot.signals ?? {}) },
      winRate: { ...EMPTY_WIN_RATE, ...(boot.winRate ?? {}) },
      trade: { ...EMPTY_TRADE, ...(boot.trade ?? {}) },
      session: { ...EMPTY_SESSION, ...(boot.session ?? {}) },
      risk: { ...EMPTY_RISK, ...(boot.risk ?? {}) },
    };
  }
  const internal = snap._internal ?? {};
  return {
    ...boot,
    ...snap,
    signals: { ...EMPTY_SIGNALS, ...(boot.signals ?? {}), ...(snap.signals ?? {}) },
    winRate: { ...EMPTY_WIN_RATE, ...(boot.winRate ?? {}), ...(snap.winRate ?? {}) },
    trade: { ...EMPTY_TRADE, ...(boot.trade ?? {}), ...(snap.trade ?? {}) },
    session: { ...EMPTY_SESSION, ...(boot.session ?? {}), ...(snap.session ?? {}) },
    risk: { ...EMPTY_RISK, ...(boot.risk ?? {}), ...(snap.risk ?? {}) },
    gates: snap.gates ?? internal.gates ?? boot.gates ?? null,
    bias: snap.bias ?? boot.bias ?? null,
    sr: snap.sr ?? boot.sr ?? null,
    range: snap.range ?? boot.range ?? null,
    wick: snap.wick ?? boot.wick ?? null,
    channels: snap.channels ?? boot.channels ?? null,
  };
}
