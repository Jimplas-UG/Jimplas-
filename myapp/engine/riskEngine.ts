import { highs, lows, pivotHighConfirmAt, pivotLowConfirmAt } from './indicators';
import type { Bar, BilshenzEngineConfig, RiskSnapshot } from './types';

export function computeRisk(
  m30: Bar[],
  h4: Bar[],
  cfg: BilshenzEngineConfig,
  atrVal: number | null,
  dxyClose: number | null,
  dxyClose3BarsAgo: number | null,
  us10yClose: number | null,
  chartClose: number
): RiskSnapshot {
  const pip = cfg.pipSize;
  const atrPips = atrVal != null ? atrVal / pip : null;

  const rN = cfg.riskPctAtrNormal;
  const rE = cfg.riskPctAtrElevated;
  const rC = cfg.riskPctAtrCrisis;
  let atrMode = `CRISIS — Risk ${rC}%, widen SL`;
  if (atrPips != null && atrPips < 50) atrMode = `STANDARD — Risk ${rN}%`;
  else if (atrPips != null && atrPips < 100) atrMode = `ELEVATED — Risk ${rE}%`;

  const hh = highs(h4);
  const ll = lows(h4);
  const L = cfg.structurePivotLeft;
  const R = cfg.structurePivotRight;
  let h4sh1: number | null = null;
  let h4sh2: number | null = null;
  let h4sl1: number | null = null;
  let h4sl2: number | null = null;
  for (let conf = L + R; conf < hh.length; conf++) {
    const ph = pivotHighConfirmAt(hh, conf, L, R);
    if (ph != null) {
      h4sh2 = h4sh1;
      h4sh1 = ph;
    }
    const pl = pivotLowConfirmAt(ll, conf, L, R);
    if (pl != null) {
      h4sl2 = h4sl1;
      h4sl1 = pl;
    }
  }

  const h4n = h4.length;
  const rangePips = (i: number) => {
    if (h4n < 1 + i) return 0;
    const b = h4[h4n - 1 - i];
    return (b.h - b.l) / pip;
  };
  const h4_range_0 = rangePips(0);
  const h4_range_1 = rangePips(1);
  const h4_range_2 = rangePips(2);
  const chopZone = h4_range_0 < 40 && h4_range_1 < 40 && h4_range_2 < 40;

  const m30n = m30.length;
  const lastM30 = m30n > 0 ? m30[m30n - 1] : null;
  const barRangePips =
    lastM30 != null ? (lastM30.h - lastM30.l) / pip : 0;
  const barRangeBlocked = barRangePips > cfg.maxSpreadPips * 10;
  const brokerSpreadBlocked = cfg.currentSpreadPips > cfg.maxSpreadPips;
  const spreadBlocked = brokerSpreadBlocked || barRangeBlocked;
  const dxyRising = !!(dxyClose != null && dxyClose3BarsAgo != null && dxyClose > dxyClose3BarsAgo);
  const dxyBlocksBuy = cfg.useDxyFilter && dxyRising;
  const yieldHigh = cfg.useYieldFilter && us10yClose != null && us10yClose > cfg.yieldHighThreshold;
  const athZoneBlocked = chartClose >= cfg.athZoneLow;
  const geoMedium = cfg.geoRisk === 'MEDIUM';
  const geoHigh = cfg.geoRisk === 'HIGH';

  return {
    atrVal,
    atrPips,
    atrMode,
    chopZone,
    brokerSpreadBlocked,
    barRangeBlocked,
    spreadBlocked,
    dxyRising,
    dxyBlocksBuy,
    yieldHigh,
    athZoneBlocked,
    geoMedium,
    geoHigh,
    h4SwingHigh1: h4sh1,
    h4SwingHigh2: h4sh2,
    h4SwingLow1: h4sl1,
    h4SwingLow2: h4sl2,
  };
}
