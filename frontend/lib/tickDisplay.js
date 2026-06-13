import { isBinanceBroker } from './brokerMode';
import { engineTickSize, distanceUnit } from './tickUnits';

export function contractSizeSubtitle(riskUsd, structuralSlTicks, sizingSlTicks, tickValueUsd, cfg) {
  const unit = distanceUnit();
  const tickVal = tickValueUsd ?? cfg?.simUsdPerEngineTick ?? cfg?.simUsdPerEnginePip ?? 12.5;
  const fixed = cfg?.journalSizingSlTicks ?? cfg?.journalSizingSlPips ?? 0;
  if (fixed > 0 && structuralSlTicks > sizingSlTicks + 0.05) {
    return `$${Math.round(riskUsd)} ÷ ${sizingSlTicks}${unit} risk (${structuralSlTicks.toFixed(1)}${unit} chart SL) ÷ $${tickVal}/${unit}`;
  }
  return `$${Math.round(riskUsd)} ÷ ${structuralSlTicks > 0 ? structuralSlTicks.toFixed(1) : '—'}${unit} SL ÷ $${tickVal}/${unit}`;
}

export function beTriggerLabel(beOffsetPrice, cfg) {
  const tick = engineTickSize(cfg);
  const ticks = Math.max(1, Math.round(beOffsetPrice / tick));
  const unit = distanceUnit();
  return isBinanceBroker() ? `BE @ +${ticks} ${unit}s` : `BE @ +${ticks}p`;
}

export function sizingModeLabel(cfg) {
  const fixed = cfg?.journalSizingSlTicks ?? cfg?.journalSizingSlPips ?? 0;
  const unit = distanceUnit();
  if (fixed > 0) return `${fixed}${unit} risk contracts`;
  return isBinanceBroker() ? 'SL-sized contracts' : 'SL-sized lots';
}

/** @deprecated */
export const lotSizeSubtitle = contractSizeSubtitle;
