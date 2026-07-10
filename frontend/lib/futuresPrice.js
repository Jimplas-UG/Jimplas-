/** Smart price formatting for USDT-M futures (BTC to micro-cap alts). */
export function formatFuturesPrice(n, tickSize) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  const tick = Number(tickSize);
  if (Number.isFinite(tick) && tick > 0) {
    const decimals = Math.max(0, Math.min(8, -Math.floor(Math.log10(tick))));
    return x.toFixed(decimals);
  }
  if (x >= 1000) return x.toFixed(2);
  if (x >= 1) return x.toFixed(4);
  if (x >= 0.01) return x.toFixed(5);
  if (x >= 0.0001) return x.toFixed(6);
  return x.toFixed(8);
}

export function roundFuturesMid(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return null;
  if (x >= 1000) return parseFloat(x.toFixed(2));
  if (x >= 1) return parseFloat(x.toFixed(4));
  if (x >= 0.01) return parseFloat(x.toFixed(5));
  if (x >= 0.0001) return parseFloat(x.toFixed(6));
  return parseFloat(x.toFixed(8));
}
