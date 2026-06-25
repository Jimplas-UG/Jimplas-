/**
 * Opaque trader-facing labels — no setup names, gate ids, or formula hints.
 */

/** @returns {'BUY'|'SELL'|'WAIT'} */
export function publicSignalSide(trade) {
  if (trade?.side === 'BUY') return 'BUY';
  if (trade?.side === 'SELL') return 'SELL';
  return 'WAIT';
}

/** @returns {'READY'|'BLOCKED'|'WAIT'} */
export function publicTradeStatus(trade) {
  const side = publicSignalSide(trade);
  if (side === 'WAIT') return 'WAIT';
  return trade?.allowed ? 'READY' : 'BLOCKED';
}

/** @returns {'LOW'|'MEDIUM'|'HIGH'} */
export function publicRiskLevel(risk, geoRisk) {
  if (risk?.geoHigh || geoRisk === 'HIGH') return 'HIGH';
  if (risk?.geoMedium || geoRisk === 'MEDIUM') return 'MEDIUM';
  if (risk?.chopZone || risk?.yieldHigh || risk?.athZoneBlocked) return 'MEDIUM';
  return 'LOW';
}

export function publicStatusLine(trade) {
  const st = publicTradeStatus(trade);
  if (st === 'READY') return 'Signal active — execution permitted';
  if (st === 'BLOCKED') return 'Signal blocked — stand by';
  return 'Scanning market — no active signal';
}

export function publicSetupPill(trade) {
  const side = publicSignalSide(trade);
  if (side === 'BUY') return '▲ Long bias';
  if (side === 'SELL') return '▼ Short bias';
  return '◎ Monitoring';
}

export function publicSessionLabel(session) {
  return session?.sessionLabel || session?.name || 'STANDBY';
}

/** Map internal execute-block text to opaque codes for logs. */
export function publicBlockReason(reason) {
  if (!reason || typeof reason !== 'string') return 'DESK_BLOCKED';
  if (reason.startsWith('RISK_')) {
    const map = {
      RISK_EMERGENCY_STOP: 'RISK_STOP',
      RISK_PAUSE_NEW_TRADES: 'RISK_PAUSED',
      RISK_API_ERRORS: 'RISK_API_HALT',
      RISK_DAILY_LOSS_LIMIT: 'RISK_DAILY_LIMIT',
      RISK_WEEKLY_LOSS_LIMIT: 'RISK_WEEKLY_LIMIT',
      RISK_DRAWDOWN_LIMIT: 'RISK_DRAWDOWN',
      RISK_MAX_OPEN_POSITIONS: 'RISK_MAX_POSITIONS',
      RISK_ASSET_EXPOSURE: 'RISK_ASSET_CAP',
      RISK_PORTFOLIO_EXPOSURE: 'RISK_EXPOSURE_CAP',
      RISK_LEVERAGE_CAP: 'RISK_LEVERAGE',
      RISK_NO_AVAILABLE_CAPITAL: 'RISK_NO_CAPITAL',
    };
    return map[reason] ?? 'RISK_LIMIT';
  }
  const r = reason.toLowerCase();
  if (r.includes('no buy') || r.includes('no sell')) return 'SIDE_BLOCKED';
  if (r.includes('spread')) return 'MARKET_BLOCKED';
  if (r.includes('max trade') || r.includes('cap')) return 'CAP_REACHED';
  if (r.includes('gate') || r.includes('block')) return 'GATES_BLOCKED';
  if (r.includes('mismatch')) return 'SYNC_BLOCKED';
  if (r.includes('missing')) return 'LEVELS_PENDING';
  return 'DESK_BLOCKED';
}

export function publicExecuteMessage(gateResult) {
  if (gateResult?.ok) return 'Order submitted';
  return publicBlockReason(gateResult?.reason);
}

/** Channel states — public labels A/B/C; p1–p3 aliases avoid blank rows in shared INTEL widgets. */
export function publicChannelStates(signals) {
  const live = (s) => !!(signals?.[`${s}Buy`] || signals?.[`${s}Sell`]);
  const p1 = live('p1') ? 'LIVE' : 'SCAN';
  const p2 = live('p2') ? 'LIVE' : 'SCAN';
  const p3 = live('p3') ? 'LIVE' : 'SCAN';
  return { a: p1, b: p2, c: p3, p1, p2, p3 };
}
