/**
 * Client engine entry — all imports for Expo Go stay in frontend/.
 * Strategy math runs on desk-api (backend); this module only has bundle + journal helpers.
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

export function nyYmdKey(tUtcMs) {
  const d = new Date(tUtcMs);
  return `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}-${d.getUTCDate()}`;
}

export function computeBilshenzSnapshot() {
  throw new Error('Strategy runs on desk-api. Start: cd backend && npm run desk-api');
}

export {
  buildSyntheticMarketBundle,
  patchBundleLast,
  sliceMarketBundleToM30End,
} from '../lib/syntheticMarket';

export { m30ToM15Bars } from '../lib/m15Bars';

export { resolveJournalOnBar, buildManualJournalEntry } from '../lib/journalClient';
