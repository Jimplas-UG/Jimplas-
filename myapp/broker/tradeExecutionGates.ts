import type { BilshenzSnapshot, TradeRecommendation } from '../engine/types';

export type TradeGateResult = { ok: true } | { ok: false; reason: string };

/** Same gates as backtest auto-trade: allowed + signal side match + geometry. */
export function canExecuteTrade(
  snapshot: BilshenzSnapshot | null | undefined,
  trade?: TradeRecommendation | null
): TradeGateResult {
  const tr = trade ?? snapshot?.trade;
  const sig = snapshot?.signals;
  if (!tr?.side || (tr.side !== 'BUY' && tr.side !== 'SELL')) {
    return { ok: false, reason: 'no BUY/SELL side' };
  }
  if (!tr.allowed) {
    const blocks = tr.blocks?.length ? tr.blocks.join('; ') : tr.reason || 'gates blocked';
    return { ok: false, reason: blocks };
  }
  const sideMatch =
    (tr.side === 'BUY' && sig?.anyBuy) || (tr.side === 'SELL' && sig?.anySell);
  if (!sideMatch) {
    return { ok: false, reason: 'signal side mismatch' };
  }
  if (tr.entry == null || !Number.isFinite(tr.entry) || tr.sl == null || !Number.isFinite(tr.sl)) {
    return { ok: false, reason: 'missing entry or SL' };
  }
  return { ok: true };
}
