/**
 * Split architecture: Expo Go never bundles backend/engine — desk-api serves snapshots.
 * Set EXPO_PUBLIC_DESK_LOCAL=1 only for intentional on-device backend bundling (advanced).
 */
export const USE_REMOTE_DESK = process.env.EXPO_PUBLIC_DESK_LOCAL !== '1';

/**
 * Desk security mode — production builds hide strategy internals.
 * Dev builds may show INTEL while still using desk-api (split architecture).
 */
export const IS_PRODUCTION_DESK =
  typeof __DEV__ !== 'undefined' ? !__DEV__ && USE_REMOTE_DESK : USE_REMOTE_DESK;

/** Show INTEL panels in dev; production + remote desk uses trader-safe UI only. */
export const SHOW_STRATEGY_INTEL = typeof __DEV__ !== 'undefined' && __DEV__;

/** Log verbose engine / gate diagnostics to console. */
export const ENABLE_DESK_DIAGNOSTICS = !IS_PRODUCTION_DESK && process.env.EXPO_PUBLIC_DESK_DIAG !== '0';

export function getDeskApiBase() {
  const base = process.env.EXPO_PUBLIC_DESK_API_URL?.trim();
  return base || 'http://127.0.0.1:8791';
}

export function deskApiHeaders() {
  const key = process.env.EXPO_PUBLIC_DESK_API_KEY?.trim();
  const headers = { 'Content-Type': 'application/json' };
  if (key) headers.Authorization = `Bearer ${key}`;
  return headers;
}
