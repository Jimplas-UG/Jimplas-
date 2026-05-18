/** M30 → M15 split for journal resolution (client-only). */

const M15_MS = 15 * 60 * 1000;

export function splitM30BarToM15(b) {
  const mid = (b.o + b.c) / 2;
  let h1 = Math.max(b.o, mid);
  let l1 = Math.min(b.o, mid);
  let h2 = Math.max(mid, b.c);
  let l2 = Math.min(mid, b.c);
  const unionH = Math.max(h1, h2);
  const unionL = Math.min(l1, l2);
  if (b.h > unionH) {
    const extra = b.h - unionH;
    if (h1 >= h2) h1 += extra;
    else h2 += extra;
  }
  if (b.l < unionL) {
    const extra = unionL - b.l;
    if (l1 <= l2) l1 -= extra;
    else l2 -= extra;
  }
  return [
    { t: b.t, o: b.o, h: h1, l: l1, c: mid },
    { t: b.t + M15_MS, o: mid, h: h2, l: l2, c: b.c },
  ];
}

export function m30ToM15Bars(m30) {
  const out = [];
  for (const b of m30) out.push(...splitM30BarToM15(b));
  return out;
}
