/** Lightweight M30 → HTF bundle builder for live broker feed (no strategy logic). */

function compressBars(m30, factor) {
  if (!m30.length) return [];
  const out = [];
  for (let i = factor - 1; i < m30.length; i += factor) {
    const slice = m30.slice(i - factor + 1, i + 1);
    const t = slice[0].t;
    const o = slice[0].o;
    const c = slice[slice.length - 1].c;
    const h = Math.max(...slice.map((b) => b.h));
    const l = Math.min(...slice.map((b) => b.l));
    out.push({ t, o, h, l, c });
  }
  return out;
}

function syntheticMacroSeries(m30) {
  const closes = m30.map((b) => b.c);
  const dxyCloseSeries = closes.map((c, i) => 99 + Math.sin(i / 40) * 0.8);
  const us10yCloseSeries = closes.map((c, i) => 4.2 + Math.sin(i / 55) * 0.05);
  return { dxyCloseSeries, us10yCloseSeries };
}

function alignMacroCloses(m30Len, macroBars) {
  const closes = macroBars.map((b) => b.c);
  const out = [];
  for (let i = 0; i < m30Len; i++) {
    const j = macroBars.length - m30Len + i;
    out.push(j >= 0 ? closes[j] : closes[closes.length - 1]);
  }
  return out;
}

export function buildBundleFromM30Bars(m30, opts) {
  const L = m30.length;
  const syn = syntheticMacroSeries(m30);
  const dxyCloseSeries = opts?.dxyM30?.length ? alignMacroCloses(L, opts.dxyM30) : syn.dxyCloseSeries;
  const us10yCloseSeries = opts?.us10yM30?.length ? alignMacroCloses(L, opts.us10yM30) : syn.us10yCloseSeries;
  return {
    m30,
    h4: compressBars(m30, 8),
    d1: compressBars(m30, 48),
    w1: compressBars(m30, 48 * 5),
    mn1: compressBars(m30, 48 * 22),
    dxyCloseSeries,
    us10yCloseSeries,
  };
}
