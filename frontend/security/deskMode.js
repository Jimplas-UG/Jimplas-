/**
 * Split architecture: Expo Go never bundles backend/engine — desk-api serves snapshots.
 */
import { getDeskApiKey, getDeskApiUrl, isDeskRemote } from '../lib/envConfig';

export const USE_REMOTE_DESK = isDeskRemote();

export const IS_PRODUCTION_DESK =
  typeof __DEV__ !== 'undefined' ? !__DEV__ && USE_REMOTE_DESK : USE_REMOTE_DESK;

export const SHOW_STRATEGY_INTEL = typeof __DEV__ !== 'undefined' && __DEV__;

export const ENABLE_DESK_DIAGNOSTICS = !IS_PRODUCTION_DESK && process.env.EXPO_PUBLIC_DESK_DIAG !== '0';

export function getDeskApiBase() {
  return getDeskApiUrl();
}

export function deskApiHeaders() {
  const key = getDeskApiKey();
  const headers = { 'Content-Type': 'application/json' };
  if (key) headers.Authorization = `Bearer ${key}`;
  return headers;
}
