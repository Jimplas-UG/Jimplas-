/**
 * Live USDT-M linear floating PnL from mark vs entry (keeps UI updating while REST cools).
 *
 * HARD RULE: never apply a scanner/chart tick from symbol A to open legs on symbol B.
 * Wrong-symbol marks (QNT@248 on US@0.03) produced phantom floating PnL beyond exposure.
 * All UI floating PnL MUST go through these helpers — do not recompute (mark-entry)*qty ad hoc.
 */

/** Reject marks that cannot be the same instrument as entry (e.g. QNT@248 on US@0.03). */
export const MAX_MARK_REL_MOVE = 0.45;

/** Cap |floating| vs entry notional so polluted sticky never shows beyond ~exposure. */
export const MAX_PNL_NOTIONAL_MULT = 1.25;

export function legSideOf(pos) {
  return String(
    pos?.positionSide || pos?.leg || (pos?.type === 'SELL' ? 'SHORT' : 'LONG'),
  ).toUpperCase();
}

function stickyProfit(pos) {
  const sticky = Number(pos?.profit ?? 0);
  return Number.isFinite(sticky) ? sticky : 0;
}

function entryOf(pos) {
  return Number(pos?.price_open ?? pos?.entryPrice ?? 0);
}

function volOf(pos) {
  return Number(pos?.volume ?? pos?.qty ?? 0);
}

function notionalOf(pos) {
  const entry = entryOf(pos);
  const vol = volOf(pos);
  return entry > 0 && vol > 0 ? entry * vol : 0;
}

function clampToExposure(value, notional) {
  const v = Number(value);
  if (!Number.isFinite(v)) return 0;
  if (!(notional > 0)) return v;
  const cap = notional * MAX_PNL_NOTIONAL_MULT;
  if (Math.abs(v) > cap) return Math.sign(v) * cap;
  return v;
}

/** True when mark is close enough to entry to be the same market. */
export function isPlausibleMark(entryPrice, markPrice, maxRel = MAX_MARK_REL_MOVE) {
  const entry = Number(entryPrice);
  const mark = Number(markPrice);
  if (!(entry > 0) || !(mark > 0)) return false;
  return Math.abs(mark - entry) / entry <= maxRel;
}

/**
 * Resolve a display/live mark for one leg.
 * Live overlay only when livePriceSymbol matches pos.symbol AND mark is plausible vs entry.
 * Never returns a cross-instrument or polluted price_current.
 */
export function resolveLegMark(pos, livePrice = null, livePriceSymbol = null) {
  const entry = entryOf(pos);
  const posSym = String(pos?.symbol || '').toUpperCase();
  const tickSym = String(livePriceSymbol || '').toUpperCase();
  const tickPx = Number(livePrice);

  if (tickSym && posSym && tickSym === posSym && tickPx > 0 && isPlausibleMark(entry, tickPx)) {
    return tickPx;
  }

  const own = Number(pos?.price_current ?? pos?.markPrice);
  if (own > 0 && isPlausibleMark(entry, own)) return own;

  return null;
}

/**
 * Approximate unrealized PnL for one linear futures leg.
 * Falls back to exchange sticky profit (clamped to exposure) when mark is missing/absurd.
 *
 * @param {object} pos
 * @param {number|null} markPrice
 * @param {string|null} livePriceSymbol — when set, markPrice is only used if it matches pos.symbol
 */
export function liveLegProfit(pos, markPrice = null, livePriceSymbol = null) {
  const entry = entryOf(pos);
  const vol = volOf(pos);
  const notional = notionalOf(pos);
  const posSym = String(pos?.symbol || '').toUpperCase();
  const tickSym = livePriceSymbol ? String(livePriceSymbol).toUpperCase() : null;
  const candidate = Number(markPrice);

  let mark = null;
  if (candidate > 0 && isPlausibleMark(entry, candidate)) {
    if (!tickSym || tickSym === posSym) mark = candidate;
  }
  if (mark == null) {
    const own = Number(pos?.price_current ?? pos?.markPrice);
    if (own > 0 && isPlausibleMark(entry, own)) mark = own;
  }

  if (!(mark > 0) || !(entry > 0) || !(vol > 0)) {
    return clampToExposure(stickyProfit(pos), notional);
  }

  const side = legSideOf(pos);
  const short = side === 'SHORT' || side === 'SELL' || pos?.type === 'SELL';
  const computed = short ? (entry - mark) * vol : (mark - entry) * vol;
  if (!Number.isFinite(computed)) return clampToExposure(stickyProfit(pos), notional);

  const sticky = stickyProfit(pos);
  const absComputed = Math.abs(computed);
  const absSticky = Math.abs(sticky);
  const stickyOk = absSticky > 0 && absSticky <= notional * MAX_PNL_NOTIONAL_MULT;
  const cap = Math.max(notional * MAX_PNL_NOTIONAL_MULT, stickyOk ? absSticky * 3 : 0, 50);
  if (absComputed > cap) {
    if (stickyOk) return sticky;
    return clampToExposure(computed, notional);
  }
  return computed;
}

/**
 * @param {object[]} positions
 * @param {Record<string, number>|number|null} marks — map by symbol, or single mark for one symbol
 * @param {string|null} quoteSymbol — when marks is a number, ONLY apply to this symbol (required)
 */
export function liveFloatingTotal(positions, marks, quoteSymbol = null) {
  const rows = Array.isArray(positions) ? positions : [];
  if (!rows.length) return 0;
  const q = quoteSymbol ? String(quoteSymbol).toUpperCase() : null;
  const single = typeof marks === 'number' ? marks : null;
  const map = marks && typeof marks === 'object' ? marks : null;
  return rows.reduce((sum, p) => {
    const sym = String(p?.symbol || '').toUpperCase();
    let mark = null;
    let markSym = null;
    if (map && Number(map[sym]) > 0) {
      mark = Number(map[sym]);
      markSym = sym;
    } else if (single != null && Number.isFinite(single) && q && sym === q) {
      // Require explicit quoteSymbol — never paint one mark onto every open leg.
      mark = single;
      markSym = q;
    }
    return sum + liveLegProfit(p, mark, markSym);
  }, 0);
}

/** Prefer account with real balances over a cool-path stub. */
export function mergeStickyAccount(prev, next) {
  if (!next) return prev ?? null;
  const nextHas =
    next.balance != null || next.equity != null || (next.profit != null && !next.stale);
  const prevHas = prev && (prev.balance != null || prev.equity != null || prev.profit != null);
  if (!nextHas && prevHas) {
    return {
      ...prev,
      stale: true,
      warning: next.warning || prev.warning,
    };
  }
  if (next.stale && prevHas && next.balance == null && next.equity == null) {
    return {
      ...prev,
      stale: true,
      warning: next.warning || prev.warning,
      profit: next.profit != null ? next.profit : prev.profit,
    };
  }
  return next;
}
