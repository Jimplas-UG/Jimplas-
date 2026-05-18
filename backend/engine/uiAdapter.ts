import type { BilshenzSnapshot } from './types';

export function mapSessionBitsFromEngine(s: BilshenzSnapshot['session']) {
  return {
    s1: s.preLondon,
    s2: s.london,
    s3: s.newYork,
    act: s.inSession,
    sessLabel: s.sessionLabel,
  };
}

/** Aligns engine output with the `sr` aggregate used in App.js lists and verdict cards. */
export function mapSrFromEngine(snap: BilshenzSnapshot, livePrice: number, C: Record<string, string>) {
  const effPip = 0.1;
  const { sr, range } = snap;
  const immRes = sr.nearestRes;
  const immSup = sr.nearestSup;
  const poiRes = sr.poiRes ?? immRes;
  const poiSup = sr.poiSup ?? immSup;

  const distRes = immRes != null ? ((immRes - livePrice) / effPip).toFixed(1) : '—';
  const distSup = immSup != null ? ((livePrice - immSup) / effPip).toFixed(1) : '—';
  const distPoiRes = poiRes != null && poiRes !== immRes ? ((poiRes - livePrice) / effPip).toFixed(1) : distRes;
  const distPoiSup = poiSup != null && poiSup !== immSup ? ((livePrice - poiSup) / effPip).toFixed(1) : distSup;

  const bullPips = range.bullPips;
  const bearPips = range.bearPips;
  const bullClean = range.bullClean;
  const bearClean = range.bearClean;

  let verdictLabelColor = C.dim;
  let verdictBg = 'transparent';
  let verdictBorder = C.border;
  let verdictVal = '⛔ NO TRADE';
  let verdictValColor = C.amber;
  let verdictSub = 'Neither path qualifies ≥25 pips';

  if (bullClean && bearClean) {
    verdictBorder = 'rgba(201,168,76,0.5)';
    verdictBg = 'rgba(201,168,76,0.05)';
    verdictLabelColor = C.gold;
    verdictValColor = C.goldL;
    verdictVal = '▲▼ BOTH SIDES TRADEABLE';
    verdictSub = 'Follow HTF bias for direction';
  } else if (bullClean) {
    verdictBorder = 'rgba(0,230,118,0.5)';
    verdictBg = 'rgba(0,230,118,0.05)';
    verdictLabelColor = C.green;
    verdictValColor = C.green;
    verdictVal = '▲ BUY ONLY';
    verdictSub = 'Bull path clean · Bear path blocked';
  } else if (bearClean) {
    verdictBorder = 'rgba(255,61,87,0.5)';
    verdictBg = 'rgba(255,61,87,0.05)';
    verdictLabelColor = C.red;
    verdictValColor = C.red;
    verdictVal = '▼ SELL ONLY';
    verdictSub = 'Bear path clean · Bull path blocked';
  }

  const flipSup = sr.flipSupLevel;
  const flipRes = sr.flipResLevel;

  return {
    currentPrice: livePrice,
    immRes,
    immSup,
    poiRes,
    poiSup,
    distRes,
    distSup,
    distPoiRes,
    distPoiSup,
    bullPips,
    bearPips,
    bullChop: range.bullChop,
    bearChop: range.bearChop,
    bullClean,
    bearClean,
    verdictBg,
    verdictBorder,
    verdictLabelColor,
    verdictVal,
    verdictValColor,
    verdictSub,
    pos: immRes && immSup ? 'Inside Range' : immRes ? 'Below All Resistance' : 'Above All Support',
    flipSup,
    flipRes,
    flipNearFlipSup: !!(flipSup != null && immSup != null && Math.abs(flipSup - immSup) < effPip * 8),
  };
}
