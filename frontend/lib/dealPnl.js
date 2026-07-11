/** Client-side guard when backend has not yet deployed deal P&L sanitization. */

export function dealNotional(deal) {
  const quote = Number(deal?.quote_qty ?? deal?.quoteQty ?? 0);
  if (Number.isFinite(quote) && quote > 0) return quote;
  const vol = Number(deal?.volume ?? 0);
  const px = Number(deal?.price ?? 0);
  if (!Number.isFinite(vol) || !Number.isFinite(px)) return 0;
  return vol * px;
}

export function isPhantomDealPnl(deal) {
  const profit = Number(deal?.profit ?? deal?.realized_pnl ?? 0);
  if (!Number.isFinite(profit) || Math.abs(profit) < 1e-9) return false;
  const notional = dealNotional(deal);
  if (notional <= 0) return Math.abs(profit) > 2500;
  return Math.abs(profit) > Math.max(notional * 8, 2500);
}

export function displayDealPnl(deal) {
  const profit = Number(deal?.profit ?? deal?.realized_pnl ?? 0);
  if (!Number.isFinite(profit)) return 0;
  if (isPhantomDealPnl(deal)) return 0;
  return profit;
}

export function isCloseDeal(deal) {
  if (deal?.is_close === true) return true;
  const pl = displayDealPnl(deal);
  return Math.abs(pl) > 1e-9;
}
