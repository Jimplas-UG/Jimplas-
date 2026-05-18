/**
 * Production client stub — engine logic runs on strategy-api only.
 * Metro aliases `../engine` to this file when EXPO_PUBLIC_DESK_REMOTE=1.
 */

export const defaultBilshenzConfig = {
  pipSize: 0.1,
  maxDailyTrades: 3,
  simUsdPerEnginePip: 12.5,
  journalSizingSlPips: 0,
  riskPctAtrNormal: 1,
  beOffset: 1.2,
  maxSpreadPips: 3.5,
  minRangePips: 25,
  athZoneLow: 0,
  athZoneHigh: 0,
  useLegacyTpClampOnly: true,
  tp1MinRewardPips: 10,
  tp1MaxRewardPips: 28,
};

export function computeBilshenzSnapshot() {
  throw new Error('Desk engine is server-only. Set EXPO_PUBLIC_DESK_API_URL and run npm run desk-api.');
}

export function buildSyntheticMarketBundle() {
  throw new Error('Desk engine is server-only.');
}

export function patchBundleLast(b) {
  return b;
}

export function sliceMarketBundleToM30End(b) {
  return b;
}

export function m30ToM15Bars() {
  return [];
}

export function buildManualJournalEntry() {
  return null;
}

export function resolveJournalOnBar(rows) {
  return rows ?? [];
}

export function nyYmdKey(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}-${d.getUTCDate()}`;
}

export { mapJournalToHistRows } from '../lib/journalHistMap';
export { mapSessionBitsFromEngine, mapSrFromEngine } from '../lib/uiAdapter';
export { buildBundleFromM30Bars } from '../lib/marketBundle';
